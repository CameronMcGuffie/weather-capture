"""Read-only endpoints for an AI agent (OpenClaw) to pull weather data.

There is deliberately no authentication: the service is only reachable on the
local network. Responses are self-describing (units and conventions travel
with the data) because the consumer can't ask what a field means.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import Database
from app.dependencies import get_database, get_ingestion_manager
from app.ingestion import RTL433Manager
from app.readings import (
    adjust_rain,
    as_utc,
    bucket_rain,
    compass_point,
    dew_point_c,
    feels_like_c,
    rain_total,
    round_or_none,
    wind_direction,
)
from app.schemas import (
    OpenClawCurrent,
    OpenClawSeries,
    OpenClawSnapshot,
    OpenClawStation,
    OpenClawWindow,
    SeriesPoint,
    Stat,
)

router = APIRouter(prefix="/api/openclaw", tags=["openclaw"])

_DEFAULT_WINDOWS = "1h,12h,24h,7d,30d"
_WINDOW_PATTERN = re.compile(r"(\d{1,4})([hd])")
_MAX_WINDOWS = 8
_MAX_WINDOW_HOURS = 24 * 366
_MAX_SERIES_POINTS = 5000
# `auto` resolution aims for a few hundred points at most: the consumer is an
# agent reading the response into its context, so a day of per-minute
# buckets (over 200 KB) would be a poor default.
_AUTO_MINUTE_MAX_HOURS = 3
_AUTO_HOURLY_MAX_HOURS = 24 * 14
_FIELD_GROUPS = ("temperature", "humidity", "wind", "rain")

_UNITS = {
    "temperature_c": "degrees Celsius",
    "humidity": "percent relative humidity",
    "wind_avg_km_h": "kilometres per hour (average wind speed)",
    "wind_gust_km_h": "kilometres per hour (gust)",
    "wind_gust_max_km_h": "kilometres per hour (strongest gust in the window)",
    "wind_from_deg": "degrees clockwise from north; the direction the wind blows FROM (270 = a westerly)",
    "feels_like_c": "degrees Celsius; apparent temperature (humidity and wind included), Bureau of Meteorology formula",
    "dew_point_c": "degrees Celsius; the higher it is, the muggier the air feels",
    "rain_mm": "millimetres",
    "rain_since_tracking_began_mm": "millimetres",
}

_SNAPSHOT_ONLY_UNITS = {"rain_since_tracking_began_mm", "wind_gust_max_km_h", "feels_like_c", "dew_point_c"}

_NOTES = [
    "All timestamps are UTC (ISO 8601). Convert to the person's local time before quoting a time to them.",
    "rain_mm in a window or series bucket is the rain that FELL during that period. "
    "rain_since_tracking_began_mm is a lifetime total since the first stored reading, not a daily figure.",
    "wind_from_deg / wind_from give the direction the wind comes FROM (meteorological convention): "
    "a west wind is 270 / 'W'. Over a window it is the prevailing direction, not a simple average.",
    "If station.is_stale is true or reading_age_seconds is large, the 'current' values are out of date; say so.",
    "Any field is null when no reading carrying that measurement exists in the period.",
]


def _parse_windows(spec: str) -> list[tuple[str, int]]:
    windows: list[tuple[str, int]] = []
    for token in (part.strip().lower() for part in spec.split(",") if part.strip()):
        match = _WINDOW_PATTERN.fullmatch(token)
        if match is None:
            raise HTTPException(
                status_code=400,
                detail=f"invalid window {token!r}: use a whole number followed by h or d, e.g. 1h, 24h, 7d",
            )
        hours = int(match[1]) * (24 if match[2] == "d" else 1)
        if not 1 <= hours <= _MAX_WINDOW_HOURS:
            raise HTTPException(status_code=400, detail=f"window {token!r} must be between 1h and 366d")
        if all(token != existing for existing, _ in windows):
            windows.append((token, hours))

    if not windows:
        raise HTTPException(status_code=400, detail="at least one window is required")
    if len(windows) > _MAX_WINDOWS:
        raise HTTPException(status_code=400, detail=f"at most {_MAX_WINDOWS} windows per request")
    return windows


def _parse_fields(spec: str | None) -> set[str]:
    if spec is None or not spec.strip():
        return set(_FIELD_GROUPS)
    selected = {part.strip().lower() for part in spec.split(",") if part.strip()}
    unknown = selected - set(_FIELD_GROUPS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown field group(s) {sorted(unknown)}: choose from {', '.join(_FIELD_GROUPS)}",
        )
    return selected


def _stat(row: aiosqlite.Row, prefix: str, digits: int) -> Stat:
    return Stat(
        min=round_or_none(row[f"{prefix}_min"], digits),
        max=round_or_none(row[f"{prefix}_max"], digits),
        avg=round_or_none(row[f"{prefix}_avg"], digits),
    )


def _build_window(label: str, hours: int, start: datetime, end: datetime, row: aiosqlite.Row) -> OpenClawWindow:
    rain_mm: float | None = None
    if row["rain_first_mm"] is not None and row["rain_last_mm"] is not None:
        # The reset-aware total only ever climbs, so last minus first is the
        # rain that fell inside the window.
        rain_mm = round_or_none(row["rain_last_mm"] - row["rain_first_mm"], 2)

    wind_from_deg, wind_from = wind_direction(row["wind_dir_sin"], row["wind_dir_cos"])
    return OpenClawWindow(
        window=label,
        hours=hours,
        start=start,
        end=end,
        readings=row["readings"],
        temperature_c=_stat(row, "temperature_c", 1),
        humidity=_stat(row, "humidity", 0),
        wind_avg_km_h=_stat(row, "wind_avg_km_h", 1),
        wind_gust_max_km_h=round_or_none(row["wind_gust_max_km_h"], 1),
        wind_from_deg=wind_from_deg,
        wind_from=wind_from,
        rain_mm=rain_mm,
    )


@router.get(
    "",
    response_model=OpenClawSnapshot,
    summary="Weather snapshot: current conditions, recent-period stats and station health",
    description=(
        "One call that answers most questions: what it is like right now, how the last hour / 12 hours / "
        "day / week / month looked (min, max and average temperature and humidity, wind, strongest gust, "
        "prevailing wind direction, rain that fell), and whether the station is alive. "
        "Use `windows` to choose the periods. For a time series or a specific past period use "
        "`/api/openclaw/series`. Units and conventions are included in the response."
    ),
)
async def get_snapshot(
    windows: str = Query(
        _DEFAULT_WINDOWS,
        description="Comma-separated look-back periods, each a whole number plus h (hours) or d (days), "
        "e.g. `1h,6h,24h,7d`. Up to 8, each between 1h and 366d.",
    ),
    database: Database = Depends(get_database),
    manager: RTL433Manager = Depends(get_ingestion_manager),
) -> OpenClawSnapshot:
    parsed = _parse_windows(windows)
    now = datetime.now(timezone.utc)

    latest = await database.fetch_latest()
    current: OpenClawCurrent | None = None
    observed_at: datetime | None = None
    model: str | None = None
    sensor_id: str | None = None
    battery_ok: bool | None = None
    if latest is not None:
        decoded = json.loads(latest["decoded_data"])
        observed_at = as_utc(datetime.fromisoformat(latest["timestamp"]))
        baseline = await database.fetch_rain_baseline_mm()
        wind_from_deg = decoded.get("wind_dir_deg")
        temperature, humidity, wind = decoded.get("temperature_c"), decoded.get("humidity"), decoded.get("wind_avg_km_h")
        model = decoded.get("model")
        sensor_id = str(decoded["id"]) if decoded.get("id") is not None else None
        battery_ok = None if decoded.get("battery_ok") is None else bool(decoded["battery_ok"])
        current = OpenClawCurrent(
            observed_at=observed_at,
            temperature_c=decoded.get("temperature_c"),
            humidity=decoded.get("humidity"),
            wind_avg_km_h=decoded.get("wind_avg_km_h"),
            wind_gust_km_h=decoded.get("wind_max_km_h"),
            wind_from_deg=wind_from_deg,
            wind_from=compass_point(wind_from_deg) if wind_from_deg is not None else None,
            feels_like_c=(
                round_or_none(feels_like_c(temperature, humidity, wind), 1)
                if temperature is not None and humidity is not None and wind is not None
                else None
            ),
            dew_point_c=(
                round_or_none(dew_point_c(temperature, humidity), 1)
                if temperature is not None and humidity is not None
                else None
            ),
            rain_since_tracking_began_mm=round_or_none(adjust_rain(rain_total(decoded), baseline), 2),
            uv=decoded.get("uv"),
            uvi=decoded.get("uvi"),
            light_lux=decoded.get("light_lux"),
        )

    window_stats = []
    for label, hours in parsed:
        start = now - timedelta(hours=hours)
        window_stats.append(_build_window(label, hours, start, now, await database.fetch_window_stats(start, now)))

    return OpenClawSnapshot(
        generated_at=now,
        station=OpenClawStation(
            model=model,
            sensor_id=sensor_id,
            battery_ok=battery_ok,
            ingestion_status=manager.state.status.value,
            is_stale=manager.is_stale(),
            last_reading_at=observed_at,
            reading_age_seconds=None if observed_at is None else round((now - observed_at).total_seconds()),
        ),
        current=current,
        windows=window_stats,
        units=_UNITS,
        notes=_NOTES,
    )


def _build_point(row: aiosqlite.Row, rain_mm: float | None, selected: set[str]) -> SeriesPoint:
    values: dict[str, Any] = {"timestamp": row["bucket"]}
    if "temperature" in selected:
        values["temperature_c"] = round_or_none(row["temperature_c"], 1)
        values["temperature_c_min"] = round_or_none(row["temperature_c_min"], 1)
        values["temperature_c_max"] = round_or_none(row["temperature_c_max"], 1)
    if "humidity" in selected:
        values["humidity"] = round_or_none(row["humidity"], 0)
        values["humidity_min"] = round_or_none(row["humidity_min"], 0)
        values["humidity_max"] = round_or_none(row["humidity_max"], 0)
    if "wind" in selected:
        wind_from_deg, wind_from = wind_direction(row["wind_dir_sin"], row["wind_dir_cos"])
        values["wind_avg_km_h"] = round_or_none(row["wind_avg_km_h"], 1)
        values["wind_avg_km_h_min"] = round_or_none(row["wind_avg_km_h_min"], 1)
        values["wind_avg_km_h_max"] = round_or_none(row["wind_avg_km_h_max"], 1)
        values["wind_gust_km_h"] = round_or_none(row["wind_max_km_h"], 1)
        values["wind_from_deg"] = wind_from_deg
        values["wind_from"] = wind_from
    if "rain" in selected:
        values["rain_mm"] = rain_mm
    return SeriesPoint(**values)


def _format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


@router.get(
    "/series",
    response_model=OpenClawSeries,
    response_model_exclude_none=True,
    summary="Time series of weather readings, aggregated per minute, hour or day",
    description=(
        "Readings aggregated into buckets over a look-back window ending now (or at `end`). Each bucket has "
        "the average, minimum and maximum of temperature, humidity and wind, the strongest gust, the "
        "prevailing wind direction, and the rain that fell in that bucket. Fields with no data are omitted. "
        "Use `fields` to trim the response, and a coarser `resolution` for long windows. "
        "For every raw reading as a file, use `/api/export`."
    ),
)
async def get_series(
    hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS, description="How far back from `end` to look, in hours."),
    end: datetime | None = Query(
        None,
        description="End of the window, ISO 8601. Prefer a trailing Z (2026-07-04T08:00:00Z); a time with no "
        "offset is taken as UTC, and a +hh:mm offset must be URL-encoded as %2Bhh:mm. Defaults to now. "
        "Set it to look at a past period, e.g. yesterday.",
    ),
    resolution: Literal["auto", "minute", "hourly", "daily"] = Query(
        "auto",
        description="Bucket size. `auto` picks one that keeps the response compact: minute buckets for windows up to 3h, hourly up to 14 days, daily beyond.",
    ),
    utc_offset_minutes: int = Query(
        0,
        ge=-840,
        le=840,
        description="Only used for `daily` buckets: the timezone offset that defines where a day starts, "
        "in minutes east of UTC (UTC+10 is 600). The first and last day may be partial.",
    ),
    fields: str | None = Query(
        None,
        description=f"Comma-separated groups to include, from: {', '.join(_FIELD_GROUPS)}. Defaults to all.",
    ),
    database: Database = Depends(get_database),
) -> OpenClawSeries:
    selected = _parse_fields(fields)
    window_end = as_utc(end) if end is not None else datetime.now(timezone.utc)
    window_start = window_end - timedelta(hours=hours)

    chosen: Literal["minute", "hourly", "daily"]
    if resolution != "auto":
        chosen = resolution
    elif hours <= _AUTO_MINUTE_MAX_HOURS:
        chosen = "minute"
    elif hours <= _AUTO_HOURLY_MAX_HOURS:
        chosen = "hourly"
    else:
        chosen = "daily"
    estimated_points = {"minute": hours * 60, "hourly": hours, "daily": hours // 24 + 2}[chosen]
    if estimated_points > _MAX_SERIES_POINTS:
        raise HTTPException(
            status_code=400,
            detail=f"{hours}h at {chosen} resolution is about {estimated_points} points "
            f"(limit {_MAX_SERIES_POINTS}): use a coarser resolution or a shorter window",
        )

    if chosen == "minute":
        rows = await database.fetch_minute_aggregates(window_start, window_end)
    elif chosen == "hourly":
        rows = await database.fetch_hourly_aggregates(window_start, window_end)
    else:
        rows = await database.fetch_daily_aggregates(window_start, window_end, utc_offset_minutes)

    rain = bucket_rain(rows)
    points = [_build_point(row, rain[index], selected) for index, row in enumerate(rows)]
    return OpenClawSeries(
        start=window_start,
        end=window_end,
        resolution=chosen,
        timestamp_meaning=(
            f"calendar date in {_format_offset(utc_offset_minutes)}"
            if chosen == "daily"
            else "start of the bucket, UTC (ISO 8601)"
        ),
        point_count=len(points),
        units={key: value for key, value in _UNITS.items() if key not in _SNAPSHOT_ONLY_UNITS},
        points=points,
    )
