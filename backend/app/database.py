from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    raw_payload TEXT NOT NULL,
    decoded_data JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weather_readings_timestamp ON weather_readings (timestamp);
"""


# rain_total_mm is a reset-aware running total computed at ingest time (see
# RTL433Manager); older rows recorded before that existed fall back to the
# sensor's raw cumulative value, which is equivalent as long as no reset had
# happened yet.
_RAIN_TOTAL_EXPR = "COALESCE(json_extract(decoded_data, '$.rain_total_mm'), json_extract(decoded_data, '$.rain_mm'))"


def _aggregate_query(bucket_expr: str) -> str:
    return f"""
        SELECT
            {bucket_expr} AS bucket,
            AVG(json_extract(decoded_data, '$.temperature_c')) AS temperature_c,
            AVG(json_extract(decoded_data, '$.humidity')) AS humidity,
            AVG(json_extract(decoded_data, '$.wind_avg_km_h')) AS wind_avg_km_h,
            MAX(json_extract(decoded_data, '$.wind_max_km_h')) AS wind_max_km_h,
            AVG(json_extract(decoded_data, '$.wind_dir_deg')) AS wind_dir_deg,
            MAX({_RAIN_TOTAL_EXPR}) AS rain_mm
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

    async def insert_reading(self, timestamp: datetime, raw_payload: str, decoded_data: dict[str, Any]) -> None:
        await self.connection.execute(
            "INSERT INTO weather_readings (timestamp, raw_payload, decoded_data) VALUES (?, ?, ?)",
            (timestamp.isoformat(), raw_payload, json.dumps(decoded_data)),
        )
        await self.connection.commit()

    async def fetch_latest(self) -> aiosqlite.Row | None:
        cursor = await self.connection.execute(
            "SELECT id, timestamp, raw_payload, decoded_data FROM weather_readings "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        return await cursor.fetchone()

    async def fetch_raw_range(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(
            "SELECT timestamp, decoded_data FROM weather_readings "
            "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
            (start.isoformat(), end.isoformat()),
        )
        return await cursor.fetchall()

    async def fetch_minute_aggregates(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(_MINUTE_QUERY, (start.isoformat(), end.isoformat()))
        return await cursor.fetchall()

    async def fetch_hourly_aggregates(self, start: datetime, end: datetime) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(_HOURLY_QUERY, (start.isoformat(), end.isoformat()))
        return await cursor.fetchall()

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
        recent reading, used to seed the ingestion manager's in-memory rain
        tracking on startup so it continues correctly across restarts.
        """
        cursor = await self.connection.execute(
            f"SELECT json_extract(decoded_data, '$.rain_mm') AS raw_rain, "
            f"{_RAIN_TOTAL_EXPR} AS total_rain FROM weather_readings "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None or row["raw_rain"] is None or row["total_rain"] is None:
            return None
        return float(row["raw_rain"]), float(row["total_rain"])
