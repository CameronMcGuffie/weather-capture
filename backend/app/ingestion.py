from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
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

_WATCHDOG_POLL_SECONDS = 15.0

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _strip_control_chars(text: str) -> str:
    # 433MHz has no authentication, and this text gets logged (and stored)
    # verbatim; a crafted payload containing a bare \r or an ANSI escape
    # sequence would otherwise be interpreted by a terminal tailing the
    # logs, letting it forge/hide log lines. Legitimate rtl_433 JSON never
    # contains a raw control byte (the JSON spec requires them \u-escaped
    # inside string values), so this can't affect real data.
    return _CONTROL_CHARS_RE.sub("", text)


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
                    stderr=asyncio.subprocess.PIPE,
                )
                self.state.pid = self._process.pid
                self.state.started_at = datetime.now(timezone.utc)
                self.state.status = IngestionStatus.RUNNING
                backoff = self._settings.restart_backoff_seconds

                assert self._process.stdout is not None
                assert self._process.stderr is not None
                watchdog_task = asyncio.create_task(self._watch_for_stall())
                try:
                    # Both streams must be drained concurrently, not one
                    # after the other: rtl_433's own diagnostics (device
                    # detection, tuner info, errors) go to stderr, and if
                    # that pipe's buffer fills up while only stdout is being
                    # read, rtl_433 blocks on its next stderr write and
                    # silently hangs.
                    await asyncio.gather(
                        self._consume_stdout(self._process.stdout),
                        self._consume_stderr(self._process.stderr),
                    )
                finally:
                    watchdog_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await watchdog_task

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

    async def _watch_for_stall(self) -> None:
        """rtl_433 can start and keep running without ever exiting even
        though it failed to claim the USB dongle — most commonly right after
        a redeploy, if the previous container's process hasn't released the
        device yet. That leaves nothing to trigger the normal
        crash-and-restart path, so this force-kills the process if too long
        passes with no successful reading, letting the existing backoff loop
        retry from a clean process (by which point the device is normally
        free).
        """
        while True:
            await asyncio.sleep(_WATCHDOG_POLL_SECONDS)
            reference = self.state.last_reading_at or self.state.started_at
            if reference is None:
                continue
            elapsed = (datetime.now(timezone.utc) - reference).total_seconds()
            if elapsed > self._settings.watchdog_timeout_seconds:
                logger.warning(
                    "no rtl_433 reading in %.0fs (limit %.0fs); killing it to force a fresh retry",
                    elapsed,
                    self._settings.watchdog_timeout_seconds,
                )
                if self._process is not None and self._process.returncode is None:
                    self._process.kill()
                return

    async def _consume_stdout(self, stream: asyncio.StreamReader) -> None:
        async for line in stream:
            text = _strip_control_chars(line.decode("utf-8", errors="replace").strip())
            if not text:
                continue
            await self._handle_line(text)

    async def _consume_stderr(self, stream: asyncio.StreamReader) -> None:
        # rtl_433's own device/tuner diagnostics and errors (e.g. a USB
        # dongle dropping out) show up here — surfaced at INFO so they're
        # visible in the container logs by default, not just with LOG_LEVEL=debug.
        async for line in stream:
            text = _strip_control_chars(line.decode("utf-8", errors="replace").strip())
            if text:
                logger.info("rtl_433: %s", text)

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
