from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.readings import as_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    raw_payload TEXT NOT NULL,
    decoded_data JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weather_readings_timestamp ON weather_readings (timestamp);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# rain_total_mm is a reset-aware running total computed at ingest time (see
# RainTracker); older rows recorded before that existed fall back to the
# sensor's raw cumulative value, which is equivalent as long as no reset had
# happened yet.
_RAIN_TOTAL_EXPR = "COALESCE(json_extract(decoded_data, '$.rain_total_mm'), json_extract(decoded_data, '$.rain_mm'))"
_WIND_DIR_EXPR = "json_extract(decoded_data, '$.wind_dir_deg')"


def _sin_deg(value: object) -> float | None:
    return math.sin(math.radians(value)) if isinstance(value, (int, float)) else None


def _cos_deg(value: object) -> float | None:
    return math.cos(math.radians(value)) if isinstance(value, (int, float)) else None


def _bound(value: datetime) -> str:
    return as_utc(value).isoformat()


def _aggregate_query(bucket_expr: str) -> str:
    # Per-bucket MIN/MAX ride along with the averages so callers can show the
    # extremes an average hides once buckets span many readings. Wind
    # direction is returned as the mean sine and cosine (the caller turns
    # those into an angle) because averaging raw degrees is wrong near north.
    return f"""
        SELECT
            {bucket_expr} AS bucket,
            AVG(json_extract(decoded_data, '$.temperature_c')) AS temperature_c,
            MIN(json_extract(decoded_data, '$.temperature_c')) AS temperature_c_min,
            MAX(json_extract(decoded_data, '$.temperature_c')) AS temperature_c_max,
            AVG(json_extract(decoded_data, '$.humidity')) AS humidity,
            MIN(json_extract(decoded_data, '$.humidity')) AS humidity_min,
            MAX(json_extract(decoded_data, '$.humidity')) AS humidity_max,
            AVG(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h,
            MIN(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h_min,
            MAX(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h_max,
            MAX(json_extract(decoded_data, '$.wind_max_km_h')) AS wind_max_km_h,
            AVG(sin_deg({_WIND_DIR_EXPR})) AS wind_dir_sin,
            AVG(cos_deg({_WIND_DIR_EXPR})) AS wind_dir_cos,
            MIN({_RAIN_TOTAL_EXPR}) AS rain_min_mm,
            MAX({_RAIN_TOTAL_EXPR}) AS rain_max_mm
        FROM weather_readings
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY bucket
        ORDER BY bucket ASC
    """


# The trailing literal "Z" marks these as UTC; without it, a browser parsing
# this string interprets it as already being in the local timezone instead
# of converting from UTC, so the chart would display the raw UTC clock time.
_MINUTE_QUERY = _aggregate_query("strftime('%Y-%m-%dT%H:%M:00Z', timestamp)")
_HOURLY_QUERY = _aggregate_query("strftime('%Y-%m-%dT%H:00:00Z', timestamp)")
# Days are calendar days in the caller's timezone, so the bucket expression
# takes the UTC offset as a bound modifier (e.g. "+600 minutes").
_DAILY_QUERY = _aggregate_query("strftime('%Y-%m-%d', timestamp, ?)")

_WINDOW_STATS_QUERY = f"""
    SELECT
        COUNT(*) AS readings,
        MIN(json_extract(decoded_data, '$.temperature_c')) AS temperature_c_min,
        MAX(json_extract(decoded_data, '$.temperature_c')) AS temperature_c_max,
        AVG(json_extract(decoded_data, '$.temperature_c')) AS temperature_c_avg,
        MIN(json_extract(decoded_data, '$.humidity')) AS humidity_min,
        MAX(json_extract(decoded_data, '$.humidity')) AS humidity_max,
        AVG(json_extract(decoded_data, '$.humidity')) AS humidity_avg,
        MIN(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h_min,
        MAX(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h_max,
        AVG(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h_avg,
        MAX(json_extract(decoded_data, '$.wind_max_km_h')) AS wind_gust_max_km_h,
        AVG(sin_deg({_WIND_DIR_EXPR})) AS wind_dir_sin,
        AVG(cos_deg({_WIND_DIR_EXPR})) AS wind_dir_cos,
        MIN({_RAIN_TOTAL_EXPR}) AS rain_first_mm,
        MAX({_RAIN_TOTAL_EXPR}) AS rain_last_mm
    FROM weather_readings
    WHERE timestamp BETWEEN ? AND ?
"""


# Wind rose: readings under the calm threshold have no meaningful direction,
# and the rest are split by speed (roughly light / moderate / fresh / strong).
WIND_CALM_BELOW_KM_H = 1.0
WIND_BIN_EDGES_KM_H = (6.0, 20.0, 39.0)

_WIND_SPEED_EXPR = "json_extract(decoded_data, '$.wind_avg_km_h')"
_WIND_SECTOR_EXPR = f"CAST(({_WIND_DIR_EXPR} + 11.25) / 22.5 AS INTEGER) % 16"
_WIND_BIN_EXPR = (
    f"CASE WHEN {_WIND_SPEED_EXPR} < {WIND_BIN_EDGES_KM_H[0]} THEN 0 "
    f"WHEN {_WIND_SPEED_EXPR} < {WIND_BIN_EDGES_KM_H[1]} THEN 1 "
    f"WHEN {_WIND_SPEED_EXPR} < {WIND_BIN_EDGES_KM_H[2]} THEN 2 ELSE 3 END"
)

# Only the rain total per bucket, so rain charts don't pay for every aggregate.
_RAIN_BUCKET_QUERY = f"""
    SELECT {{bucket_expr}} AS bucket,
        MIN({_RAIN_TOTAL_EXPR}) AS rain_min_mm,
        MAX({_RAIN_TOTAL_EXPR}) AS rain_max_mm
    FROM weather_readings
    WHERE timestamp BETWEEN ? AND ?
    GROUP BY bucket
    ORDER BY bucket ASC
"""
_RAIN_HOURLY_QUERY = _RAIN_BUCKET_QUERY.format(bucket_expr="strftime('%Y-%m-%dT%H:00:00Z', timestamp)")
_RAIN_DAILY_QUERY = _RAIN_BUCKET_QUERY.format(bucket_expr="strftime('%Y-%m-%d', timestamp, ?)")

# The one place a column name is built into SQL: from this fixed list only.
_EXTREME_FIELDS = {
    "temperature_c": "json_extract(decoded_data, '$.temperature_c')",
    "wind_max_km_h": "json_extract(decoded_data, '$.wind_max_km_h')",
}
# Stray 433MHz noise sometimes decodes as a valid frame full of wild values.
# Such a reading is a single point that disagrees with the readings on both
# sides of it by more than the weather can change in the time between them,
# so it never counts as a record. (The readings themselves are kept untouched.)
# Per field: (the most two back-to-back readings can differ, how much more is
# allowed for each hour between them, the most allowed however far apart).
# A gust says nothing about the next gust however close together they are,
# so its limit doesn't grow.
_EXTREME_MAX_JUMP = {"temperature_c": (8.0, 5.0, 25.0), "wind_max_km_h": (100.0, 0.0, 100.0)}
_EXTREME_CANDIDATES = 200


def _hours_apart(first: str, second: str) -> float:
    gap = as_utc(datetime.fromisoformat(first)) - as_utc(datetime.fromisoformat(second))
    return abs(gap.total_seconds()) / 3600.0


class Database:
    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._connection: aiosqlite.Connection | None = None
        self._rain_baseline_mm: float | None = None

    async def connect(self) -> None:
        Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._database_path)
        self._connection.row_factory = aiosqlite.Row
        # WAL lets the ingestion writer and API readers proceed concurrently
        # without the dashboard blocking on the next incoming sensor reading.
        # busy_timeout makes a reader wait out a writer's brief commit window
        # instead of raising "database is locked" for an instant of overlap.
        await self._connection.execute("PRAGMA journal_mode=WAL;")
        await self._connection.execute("PRAGMA synchronous=NORMAL;")
        await self._connection.execute("PRAGMA busy_timeout=5000;")
        # SQLite's own trig functions are an optional compile-time extra that
        # not every build includes, so register what the wind averaging needs.
        await self._connection.create_function("sin_deg", 1, _sin_deg, deterministic=True)
        await self._connection.create_function("cos_deg", 1, _cos_deg, deterministic=True)
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected")
        return self._connection

    async def get_meta(self, key: str) -> str | None:
        cursor = await self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return None if row is None else str(row["value"])

    async def set_meta(self, key: str, value: str, *, commit: bool = True) -> None:
        await self.connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        if commit:
            await self.connection.commit()

    async def count_readings(self) -> int:
        cursor = await self.connection.execute("SELECT COUNT(*) AS n FROM weather_readings")
        row = await cursor.fetchone()
        assert row is not None
        return int(row["n"])

    async def iter_rain_history(self, batch_size: int = 5000) -> AsyncIterator[list[aiosqlite.Row]]:
        """(id, timestamp, raw rain value, stored running total) for every
        reading in time order, for repairing the running total."""
        cursor = await self.connection.execute(
            f"SELECT id, timestamp, json_extract(decoded_data, '$.rain_mm') AS raw_rain, "
            f"{_RAIN_TOTAL_EXPR} AS total_rain FROM weather_readings ORDER BY timestamp, id"
        )
        while rows := await cursor.fetchmany(batch_size):
            yield rows

    async def update_rain_totals(self, updates: Sequence[tuple[float, int]]) -> None:
        """Rewrite only the derived running total (never the raw reading).
        Left uncommitted so the caller can make it atomic with its marker."""
        await self.connection.executemany(
            "UPDATE weather_readings SET decoded_data = json_set(decoded_data, '$.rain_total_mm', ?) WHERE id = ?",
            updates,
        )

    async def insert_reading(self, timestamp: datetime, raw_payload: str, decoded_data: dict[str, Any]) -> None:
        await self.connection.execute(
            "INSERT INTO weather_readings (timestamp, raw_payload, decoded_data) VALUES (?, ?, ?)",
            (_bound(timestamp), raw_payload, json.dumps(decoded_data)),
        )
        await self.connection.commit()

    async def fetch_latest(self) -> aiosqlite.Row | None:
        cursor = await self.connection.execute(
            "SELECT id, timestamp, raw_payload, decoded_data FROM weather_readings "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        return await cursor.fetchone()

    async def iter_raw_range(
        self, start: datetime, end: datetime, batch_size: int = 2000
    ) -> AsyncIterator[list[aiosqlite.Row]]:
        """Every stored reading in the range, in batches, so a long export
        never has to hold the whole result set in memory at once."""
        cursor = await self.connection.execute(
            "SELECT timestamp, decoded_data FROM weather_readings "
            "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
            (_bound(start), _bound(end)),
        )
        while rows := await cursor.fetchmany(batch_size):
            yield rows

    async def fetch_minute_aggregates(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(_MINUTE_QUERY, (_bound(start), _bound(end)))
        return await cursor.fetchall()

    async def fetch_hourly_aggregates(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(_HOURLY_QUERY, (_bound(start), _bound(end)))
        return await cursor.fetchall()

    async def fetch_daily_aggregates(
        self, start: datetime, end: datetime, utc_offset_minutes: int
    ) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(
            _DAILY_QUERY, (f"{utc_offset_minutes:+d} minutes", _bound(start), _bound(end))
        )
        return await cursor.fetchall()

    async def fetch_window_stats(self, start: datetime, end: datetime, *, carry_in: bool = False) -> Mapping[str, Any]:
        """Extremes, averages and rain accumulation across a whole window.

        With `carry_in`, rain is counted from the last reading before the
        window, so rain that fell while the station wasn't recording (and
        showed up as one jump on the first reading back) lands in the window
        that reading belongs to instead of being lost.
        """
        cursor = await self.connection.execute(_WINDOW_STATS_QUERY, (_bound(start), _bound(end)))
        row = await cursor.fetchone()
        assert row is not None  # aggregates always return one row
        stats = dict(row)
        if carry_in:
            before = await self.fetch_rain_total_before(start)
            if before is not None and stats["rain_last_mm"] is not None:
                stats["rain_first_mm"] = min(before, stats["rain_last_mm"])
        return stats

    async def fetch_rain_total_before(self, start: datetime) -> float | None:
        """The running rain total at the last reading before `start`."""
        cursor = await self.connection.execute(
            f"SELECT {_RAIN_TOTAL_EXPR} AS total FROM weather_readings "
            f"WHERE timestamp < ? AND {_RAIN_TOTAL_EXPR} IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
            (_bound(start),),
        )
        row = await cursor.fetchone()
        return None if row is None else float(row["total"])

    async def fetch_rain_buckets(
        self, start: datetime, end: datetime, *, daily: bool, utc_offset_minutes: int = 0
    ) -> list[aiosqlite.Row]:
        if daily:
            cursor = await self.connection.execute(
                _RAIN_DAILY_QUERY, (f"{utc_offset_minutes:+d} minutes", _bound(start), _bound(end))
            )
        else:
            cursor = await self.connection.execute(_RAIN_HOURLY_QUERY, (_bound(start), _bound(end)))
        return await cursor.fetchall()

    async def fetch_rain_last_changed_at(self, current_total_mm: float, since: datetime) -> str | None:
        """When the running rain total last went up: the reading after the
        newest one that had a lower total. None if it hasn't since `since`."""
        cursor = await self.connection.execute(
            f"SELECT timestamp FROM weather_readings WHERE timestamp >= ? AND {_RAIN_TOTAL_EXPR} < ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (_bound(since), current_total_mm - 1e-6),
        )
        below = await cursor.fetchone()
        if below is None:
            return None
        cursor = await self.connection.execute(
            "SELECT MIN(timestamp) AS timestamp FROM weather_readings WHERE timestamp > ?", (below["timestamp"],)
        )
        after = await cursor.fetchone()
        return None if after is None else after["timestamp"]

    async def fetch_wind_rose(self, start: datetime, end: datetime) -> tuple[list[aiosqlite.Row], aiosqlite.Row]:
        """Reading counts per (16-point sector, speed bin), plus the totals
        needed to express them as a share of all readings with wind data."""
        bounds = (_bound(start), _bound(end))
        cursor = await self.connection.execute(
            f"SELECT {_WIND_SECTOR_EXPR} AS sector, {_WIND_BIN_EXPR} AS speed_bin, COUNT(*) AS n "
            f"FROM weather_readings WHERE timestamp BETWEEN ? AND ? AND {_WIND_DIR_EXPR} IS NOT NULL "
            f"AND {_WIND_SPEED_EXPR} >= {WIND_CALM_BELOW_KM_H} GROUP BY sector, speed_bin",
            bounds,
        )
        cells = await cursor.fetchall()
        cursor = await self.connection.execute(
            f"SELECT COUNT(*) AS readings, COALESCE(SUM({_WIND_SPEED_EXPR} < {WIND_CALM_BELOW_KM_H}), 0) AS calm "
            f"FROM weather_readings WHERE timestamp BETWEEN ? AND ? AND {_WIND_SPEED_EXPR} IS NOT NULL",
            bounds,
        )
        totals = await cursor.fetchone()
        assert totals is not None
        return cells, totals

    async def fetch_extreme(self, field: str, aggregate: str) -> Mapping[str, Any]:
        """The highest or lowest value ever recorded, and when, ignoring lone
        spikes (see _EXTREME_MAX_JUMP). Candidates are taken best first and
        each is checked against the nearest reading either side of it that
        has a value, so only a handful of rows are ever compared. A candidate
        stands if either neighbour backs it up, or if it's the only reading."""
        if field not in _EXTREME_FIELDS or aggregate not in ("MIN", "MAX"):
            raise ValueError("unsupported extreme")
        expr = _EXTREME_FIELDS[field]
        order = "DESC" if aggregate == "MAX" else "ASC"
        max_jump, extra_per_hour, ceiling = _EXTREME_MAX_JUMP[field]
        cursor = await self.connection.execute(
            f"SELECT timestamp, value FROM (SELECT timestamp, {expr} AS value FROM weather_readings) "
            f"WHERE value IS NOT NULL ORDER BY value {order}, timestamp LIMIT {_EXTREME_CANDIDATES}"
        )
        candidates = await cursor.fetchall()
        for candidate in candidates:
            neighbours = []
            for comparison, direction in (("<", "DESC"), (">", "ASC")):
                cursor = await self.connection.execute(
                    f"SELECT timestamp, {expr} AS value FROM weather_readings "
                    f"WHERE timestamp {comparison} ? AND {expr} IS NOT NULL ORDER BY timestamp {direction} LIMIT 1",
                    (candidate["timestamp"],),
                )
                row = await cursor.fetchone()
                if row is not None:
                    neighbours.append(row)
            if not neighbours or any(
                abs(candidate["value"] - neighbour["value"])
                <= min(max_jump + extra_per_hour * _hours_apart(candidate["timestamp"], neighbour["timestamp"]), ceiling)
                for neighbour in neighbours
            ):
                return {"value": candidate["value"], "timestamp": candidate["timestamp"]}
        return {"value": None, "timestamp": None}

    async def fetch_first_reading_timestamp(self) -> str | None:
        cursor = await self.connection.execute("SELECT MIN(timestamp) AS timestamp FROM weather_readings")
        row = await cursor.fetchone()
        return None if row is None else row["timestamp"]

    async def fetch_hourly_counts(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(
            "SELECT strftime('%Y-%m-%dT%H:00:00Z', timestamp) AS hour, COUNT(*) AS readings "
            "FROM weather_readings WHERE timestamp BETWEEN ? AND ? GROUP BY hour ORDER BY hour",
            (_bound(start), _bound(end)),
        )
        return await cursor.fetchall()

    async def fetch_longest_gap(self, start: datetime, end: datetime) -> aiosqlite.Row:
        """The longest silence between two consecutive readings (seconds) and
        when it ended."""
        cursor = await self.connection.execute(
            "SELECT MAX(gap_seconds) AS gap_seconds, timestamp AS ended_at FROM ("
            "  SELECT timestamp, (julianday(timestamp) - julianday(LAG(timestamp) OVER (ORDER BY timestamp))) * 86400.0"
            "    AS gap_seconds FROM weather_readings WHERE timestamp BETWEEN ? AND ?)",
            (_bound(start), _bound(end)),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row

    async def fetch_health_counts(self, start: datetime, end: datetime) -> aiosqlite.Row:
        """Readings that reported a low battery, and rain readings the
        ingestion held back as suspected glitches (their raw value is nulled
        while the running total is kept)."""
        cursor = await self.connection.execute(
            "SELECT COALESCE(SUM(json_extract(decoded_data, '$.battery_ok') = 0), 0) AS low_battery, "
            "COALESCE(SUM(json_extract(decoded_data, '$.rain_mm') IS NULL "
            "AND json_extract(decoded_data, '$.rain_total_mm') IS NOT NULL), 0) AS held_rain "
            "FROM weather_readings WHERE timestamp BETWEEN ? AND ?",
            (_bound(start), _bound(end)),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row

    async def fetch_rain_baseline_mm(self) -> float | None:
        """The sensor reports lifetime cumulative rainfall, not a daily total.

        The dashboard displays rain relative to the first-ever recorded
        value so it reads sensibly instead of showing years of accumulation.
        That first value never changes, so it's cached after the first hit.
        """
        if self._rain_baseline_mm is not None:
            return self._rain_baseline_mm

        cursor = await self.connection.execute(
            f"SELECT {_RAIN_TOTAL_EXPR} AS rain_mm FROM weather_readings "
            "WHERE json_extract(decoded_data, '$.rain_mm') IS NOT NULL "
            "ORDER BY timestamp ASC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is not None and row["rain_mm"] is not None:
            self._rain_baseline_mm = float(row["rain_mm"])
        return self._rain_baseline_mm

    async def fetch_latest_rain_state(self) -> tuple[float, float] | None:
        """The (raw sensor value, reset-aware running total) of the most
        recent trusted reading, used to seed the ingestion manager's rain
        tracking on startup so it continues correctly across restarts.

        Readings the tracker held back as suspect glitches have their raw
        value nulled, so they're skipped here rather than seeding it.
        """
        cursor = await self.connection.execute(
            f"SELECT json_extract(decoded_data, '$.rain_mm') AS raw_rain, "
            f"{_RAIN_TOTAL_EXPR} AS total_rain FROM weather_readings "
            "WHERE json_extract(decoded_data, '$.rain_mm') IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None or row["raw_rain"] is None or row["total_rain"] is None:
            return None
        return float(row["raw_rain"]), float(row["total_rain"])
