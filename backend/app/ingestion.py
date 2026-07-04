from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.config import Settings
from app.database import Database
from app.decoder import (
    compute_rain_total_mm,
    decode_payload,
    matches_expected_sensor,
    parse_payload_timestamp,
    sanitize_decoded,
)

logger = logging.getLogger("weather.ingestion")

# Defensive cap on a single rtl_433 output line; ordinary readings are a few
# hundred bytes, so anything past this is discarded before it's even parsed.
_MAX_LINE_LENGTH = 8192


def _reject_non_finite_constant(token: str) -> float:
    # json.loads otherwise happily parses "NaN"/"Infinity"/"-Infinity" even
    # though they aren't valid JSON, which would later break anything (like
    # the browser) that parses this data with a standards-compliant parser.
    raise ValueError(f"rejected non-finite JSON constant: {token}")


class IngestionStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    STOPPED = "stopped"


@dataclass
class IngestionState:
    status: IngestionStatus = IngestionStatus.STOPPED
    pid: int | None = None
    started_at: datetime | None = None
    last_reading_at: datetime | None = None
    restart_count: int = 0
    last_error: str | None = None
    ignored_count: int = 0


class RTL433Manager:
    """Owns the rtl_433 subprocess lifecycle: start, monitor, auto-restart, ingest."""

    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database
        self._process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.state = IngestionState()
        self._last_rain_raw_mm: float | None = None
        self._last_rain_total_mm: float | None = None

    def is_stale(self) -> bool:
        if self.state.last_reading_at is None:
            return self.state.status != IngestionStatus.STOPPED
        elapsed = (datetime.now(timezone.utc) - self.state.last_reading_at).total_seconds()
        return elapsed > self._settings.stale_reading_seconds

    async def start(self) -> None:
        self._stopping = False
        rain_state = await self._database.fetch_latest_rain_state()
        if rain_state is not None:
            self._last_rain_raw_mm, self._last_rain_total_mm = rain_state
        self._task = asyncio.create_task(self._run_forever(), name="rtl433-ingestion")

    async def stop(self) -> None:
        self._stopping = True
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
        if self._task is not None:
            await self._task
        self.state.status = IngestionStatus.STOPPED

    async def _run_forever(self) -> None:
        backoff = self._settings.restart_backoff_seconds
        while not self._stopping:
            self.state.status = IngestionStatus.STARTING
            try:
                command = self._settings.build_rtl_433_command()
                logger.info("starting rtl_433: %s", " ".join(command))
                self._process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self.state.pid = self._process.pid
                self.state.started_at = datetime.now(timezone.utc)
                self.state.status = IngestionStatus.RUNNING
                backoff = self._settings.restart_backoff_seconds

                assert self._process.stdout is not None
                await self._consume_stdout(self._process.stdout)

                return_code = await self._process.wait()
                self.state.last_error = f"rtl_433 exited with code {return_code}"
            except FileNotFoundError as exc:
                self.state.last_error = f"rtl_433 binary not found: {exc}"
            except Exception as exc:  # any subprocess/pipe failure must restart, never crash the app
                self.state.last_error = str(exc)
                logger.exception("rtl_433 ingestion loop failed")

            if self._stopping:
                break

            self.state.status = IngestionStatus.RESTARTING
            self.state.restart_count += 1
            logger.warning("rtl_433 stopped (%s), restarting in %.1fs", self.state.last_error, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._settings.max_restart_backoff_seconds)

        self.state.status = IngestionStatus.STOPPED

    async def _consume_stdout(self, stream: asyncio.StreamReader) -> None:
        async for line in stream:
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            await self._handle_line(text)

    async def _handle_line(self, text: str) -> None:
        # 433MHz is unlicensed and unauthenticated: a neighbor's sensor, an
        # unrelated gadget, or deliberately crafted noise can all produce a
        # line that looks plausible. Nothing below trusts it further than
        # necessary, and no failure here is allowed to propagate up and
        # force an unnecessary restart of an otherwise-healthy rtl_433.
        if len(text) > _MAX_LINE_LENGTH:
            logger.debug("discarding oversized rtl_433 line (%d bytes)", len(text))
            return

        try:
            payload = json.loads(text, parse_constant=_reject_non_finite_constant)
        except ValueError:
            # Covers malformed JSON and the NaN/Infinity rejection above.
            logger.debug("discarding malformed rtl_433 line: %s", text)
            return

        if not isinstance(payload, dict):
            logger.debug("discarding non-object rtl_433 line: %s", text)
            return

        # Debug-only so it's off by default (LOG_LEVEL=debug to enable);
        # every reading gets logged at INFO otherwise and floods the log.
        logger.debug("rtl_433 raw: %s", text)

        if not matches_expected_sensor(payload, self._settings.sensor_model_filter, self._settings.sensor_id_filter):
            self.state.ignored_count += 1
            # INFO (not debug) since this should be rare in a correctly
            # configured setup, and is the first thing to check if readings
            # seem to have stopped: it means SENSOR_MODEL_FILTER/
            # SENSOR_ID_FILTER no longer match what's actually transmitting
            # (e.g. the sensor's id changed after a battery swap).
            logger.info(
                "ignoring reading from an unexpected device (model=%r, id=%r): %s",
                payload.get("model"),
                payload.get("id"),
                text,
            )
            return

        try:
            decoded = sanitize_decoded(decode_payload(payload))
            timestamp = parse_payload_timestamp(payload)

            current_rain_mm = decoded.get("rain_mm")
            rain_total_mm = compute_rain_total_mm(current_rain_mm, self._last_rain_raw_mm, self._last_rain_total_mm)
            if rain_total_mm is not None:
                decoded["rain_total_mm"] = rain_total_mm
                self._last_rain_raw_mm = current_rain_mm
                self._last_rain_total_mm = rain_total_mm

            await self._database.insert_reading(timestamp, text, decoded)
        except Exception:  # a single bad reading must never crash ingestion
            logger.warning("discarding a reading that failed to process: %s", text, exc_info=True)
            return

        self.state.last_reading_at = datetime.now(timezone.utc)
