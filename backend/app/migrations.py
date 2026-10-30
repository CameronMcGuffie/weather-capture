"""One-off data repairs that run automatically at startup.

The app runs in a container whose database lives on a mounted volume, so a
repair can't be a script someone remembers to run: it runs by itself, once,
takes a verified backup first, and records that it has run.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database import Database
from app.decoder import repair_rain_totals

logger = logging.getLogger("weather.migrations")

_RAIN_REPAIR_MARKER = "rain_total_repair_v1"
_TOLERANCE_MM = 1e-6
# If more than this share of readings looks like noise, the classification is
# the thing that's wrong (a different sensor, say), so change nothing.
_MAX_GLITCH_FRACTION = 0.05
_MAX_LOGGED_EVENTS = 25


async def run_startup_migrations(database: Database, database_path: str) -> None:
    try:
        await _repair_rain_totals(database, Path(database_path))
    except Exception:
        # The app is more useful with an unrepaired history than not running.
        logger.exception("rain history repair failed; the readings were left as they were")
        with contextlib.suppress(Exception):
            await database.connection.rollback()


async def _backup(database: Database, path: Path) -> Path:
    existing = sorted(path.parent.glob(f"{path.name}.pre-rain-repair-*"))
    if existing:
        # A previous attempt that didn't finish left its backup; the repair
        # is all-or-nothing, so that is still a valid snapshot to fall back on.
        logger.info("using the existing backup %s", existing[-1].name)
        return existing[-1]

    size = sum(candidate.stat().st_size for candidate in path.parent.glob(f"{path.name}*") if candidate.is_file())
    free = shutil.disk_usage(path.parent).free
    if free < size * 1.25:
        raise RuntimeError(
            f"not enough free disk space to back up the database first ({free // 2**20} MB free, "
            f"{size // 2**20} MB needed); nothing was changed"
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.name}.pre-rain-repair-{stamp}")
    target = sqlite3.connect(destination)
    try:
        await database.connection.backup(target)
    finally:
        target.close()

    check = sqlite3.connect(destination)
    try:
        backed_up = check.execute("SELECT COUNT(*) FROM weather_readings").fetchone()[0]
    finally:
        check.close()
    if backed_up != await database.count_readings():
        destination.unlink(missing_ok=True)
        raise RuntimeError("the backup did not match the database, so nothing was changed")
    return destination


async def _repair_rain_totals(database: Database, path: Path) -> None:
    """Recompute every reading's running rain total from the raw values.

    Before the fix to RainTracker, a single corrupt reading could add the
    sensor's entire counter to the running total, permanently inflating every
    rain figure after it. Only the derived `rain_total_mm` is rewritten: the
    raw reading and `raw_payload` are never touched.
    """
    if await database.get_meta(_RAIN_REPAIR_MARKER) is not None:
        return

    ids: list[int] = []
    stamps: list[str] = []
    raws: list[float | None] = []
    stored: list[float | None] = []
    async for rows in database.iter_rain_history():
        for row in rows:
            ids.append(row["id"])
            stamps.append(row["timestamp"])
            raws.append(row["raw_rain"])
            stored.append(row["total_rain"])

    if not ids:
        await database.set_meta(_RAIN_REPAIR_MARKER, "done: no readings yet")
        return

    repair = repair_rain_totals(raws)
    with_rain = sum(1 for value in raws if value is not None)
    if with_rain and repair.glitch_readings > _MAX_GLITCH_FRACTION * with_rain:
        logger.warning(
            "rain repair skipped: %d of %d readings looked like noise, which is too many to trust; nothing was changed",
            repair.glitch_readings,
            with_rain,
        )
        await database.set_meta(_RAIN_REPAIR_MARKER, "skipped: too many readings classified as noise")
        return

    updates = [
        (new_total, row_id)
        for row_id, new_total, old_total in zip(ids, repair.totals, stored)
        if new_total is not None and (old_total is None or abs(new_total - old_total) > _TOLERANCE_MM)
    ]
    if not updates:
        logger.info("rain history checked: nothing needed repairing")
        await database.set_meta(_RAIN_REPAIR_MARKER, "done: nothing to repair")
        return

    backup = await _backup(database, path)
    try:
        await database.update_rain_totals(updates)
        await database.set_meta(_RAIN_REPAIR_MARKER, f"done: {len(updates)} readings repaired", commit=False)
        await database.connection.commit()
    except Exception:
        await database.connection.rollback()
        raise

    final_before = next(total for total in reversed(stored) if total is not None)
    final_after = next(total for total in reversed(repair.totals) if total is not None)
    logger.info(
        "rain history repaired: %d of %d readings corrected, %d noise readings skipped; "
        "the running total went from %.1f mm to %.1f mm (%.1f mm of phantom rain removed). Backup: %s",
        len(updates),
        len(ids),
        repair.glitch_readings,
        final_before,
        final_after,
        final_before - final_after,
        backup.name,
    )
    for index, kind, value in repair.events[:_MAX_LOGGED_EVENTS]:
        logger.info("  rain repair: %s at %s (raw reading %.1f mm)", kind, stamps[index], value)

    # The rewrite grew the write-ahead log; fold it back into the database.
    with contextlib.suppress(Exception):
        await database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")
