"""Derived views of the stored readings that the dashboard shows beyond the
basic tiles and chart: feels-like and rain status, rain bars, the wind rose,
records, station health and sunrise/sunset."""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.database import WIND_BIN_EDGES_KM_H, Database
from app.dependencies import get_database, get_ingestion_manager
from app.ingestion import RTL433Manager
from app.readings import as_utc, bucket_rain, compass_point, dew_point_c, feels_like_c, rain_total, round_or_none
from app.schemas import (
    HealthHour,
    NowResponse,
    PeriodExtreme,
    PeriodResponse,
    RainBar,
    RainBarsResponse,
    RainNow,
    RecordsResponse,
    StationHealthResponse,
    SunEvent,
    SunResponse,
    Trend,
    WindBin,
    WindRoseResponse,
    WindSector,
)
from app.sun import sun_events

router = APIRouter(prefix="/api", tags=["dashboard"])

_TREND_HOURS = 3
_TREND_SAMPLE = timedelta(minutes=15)
_LAST_RAIN_LOOKBACK = timedelta(days=90)
_RECORDS_TTL_SECONDS = 600
_MAX_PERIOD = timedelta(hours=48)
_MAX_SUN_SPAN = timedelta(days=400)
_SECTOR_NAMES = tuple(compass_point(index * 22.5) for index in range(16))


def _parse_stamp(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value))


async def _rain_between(database: Database, start: datetime, end: datetime, *, carry_in: bool = False) -> float | None:
    row = await database.fetch_window_stats(start, end, carry_in=carry_in)
    if row["rain_first_mm"] is None or row["rain_last_mm"] is None:
        return None
    return round_or_none(row["rain_last_mm"] - row["rain_first_mm"], 2)


@router.get("/now", response_model=NowResponse, summary="Derived current conditions: feels-like, dew point, trends, rain status")
async def get_now(database: Database = Depends(get_database)) -> NowResponse:
    latest = await database.fetch_latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="no readings recorded yet")

    decoded = json.loads(latest["decoded_data"])
    temperature, humidity, wind = decoded.get("temperature_c"), decoded.get("humidity"), decoded.get("wind_avg_km_h")
    dew_point = round_or_none(dew_point_c(temperature, humidity), 1) if temperature is not None and humidity is not None else None
    feels_like = (
        round_or_none(feels_like_c(temperature, humidity, wind), 1)
        if temperature is not None and humidity is not None and wind is not None
        else None
    )

    now = datetime.now(timezone.utc)
    earlier_end = now - timedelta(hours=_TREND_HOURS)
    recent = await database.fetch_window_stats(now - _TREND_SAMPLE, now)
    earlier = await database.fetch_window_stats(earlier_end - _TREND_SAMPLE, earlier_end)

    def change(field: str, digits: int) -> float | None:
        if recent[field] is None or earlier[field] is None:
            return None
        return round(recent[field] - earlier[field], digits)

    last_15 = await _rain_between(database, now - timedelta(minutes=15), now)
    last_hour = await _rain_between(database, now - timedelta(hours=1), now)

    last_rain_at: datetime | None = None
    current_total = rain_total(decoded)
    if current_total is not None:
        changed_at = await database.fetch_rain_last_changed_at(current_total, now - _LAST_RAIN_LOOKBACK)
        last_rain_at = None if changed_at is None else _parse_stamp(changed_at)

    return NowResponse(
        observed_at=_parse_stamp(latest["timestamp"]),
        feels_like_c=feels_like,
        dew_point_c=dew_point,
        trend=Trend(
            hours=_TREND_HOURS,
            temperature_c=change("temperature_c_avg", 1),
            humidity=change("humidity_avg", 0),
        ),
        rain=RainNow(
            raining=bool(last_15 and last_15 > 0),
            last_15_min_mm=last_15,
            last_hour_mm=last_hour,
            last_rain_at=last_rain_at,
        ),
    )


@router.get("/rain-bars", response_model=RainBarsResponse, summary="Rain that fell in each hour or day")
async def get_rain_bars(
    hours: int = Query(24, ge=1, le=24 * 366),
    bucket: Literal["hour", "day"] = Query("hour"),
    utc_offset_minutes: int = Query(0, ge=-840, le=840, description="For day buckets: where a day starts, minutes east of UTC"),
    database: Database = Depends(get_database),
) -> RainBarsResponse:
    if bucket == "hour" and hours > 24 * 31:
        raise HTTPException(status_code=400, detail="hourly bars are limited to 31 days; use day buckets for longer")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    rows = await database.fetch_rain_buckets(start, end, daily=bucket == "day", utc_offset_minutes=utc_offset_minutes)
    rain = bucket_rain(rows, await database.fetch_rain_total_before(start))
    return RainBarsResponse(
        start=start,
        end=end,
        bucket=bucket,
        total_mm=round(sum(value for value in rain if value is not None), 1),
        points=[RainBar(timestamp=row["bucket"], rain_mm=value) for row, value in zip(rows, rain)],
    )


def _wind_bins() -> list[WindBin]:
    edges = (1.0, *WIND_BIN_EDGES_KM_H)  # readings under 1 km/h are "calm", counted separately
    bins = []
    for index, low in enumerate(edges):
        high = edges[index + 1] if index + 1 < len(edges) else None
        label = f"{low:g}+ km/h" if high is None else f"{low:g}–{high - 1:g} km/h"
        bins.append(WindBin(label=label, min_km_h=low, max_km_h=high))
    return bins


@router.get("/wind-rose", response_model=WindRoseResponse, summary="How often the wind blew from each direction, and how hard")
async def get_wind_rose(
    hours: int = Query(24 * 30, ge=1, le=24 * 366),
    database: Database = Depends(get_database),
) -> WindRoseResponse:
    end = datetime.now(timezone.utc)
    cells, totals = await database.fetch_wind_rose(end - timedelta(hours=hours), end)
    readings, calm = int(totals["readings"]), int(totals["calm"])

    bins = _wind_bins()
    counts = [[0] * len(bins) for _ in range(16)]
    for cell in cells:
        counts[cell["sector"]][cell["speed_bin"]] = cell["n"]

    def share(count: int) -> float:
        return round(100.0 * count / readings, 1) if readings else 0.0

    sectors = [
        WindSector(direction=_SECTOR_NAMES[index], degrees=index * 22.5, counts=row, percent=share(sum(row)))
        for index, row in enumerate(counts)
    ]
    return WindRoseResponse(
        hours=hours,
        readings=readings,
        calm_percent=share(calm),
        max_sector_percent=max((sector.percent for sector in sectors), default=0.0),
        bins=bins,
        sectors=sectors,
    )


@router.get("/period", response_model=PeriodResponse, summary="High, low, peak gust and rain for a stretch of time (e.g. today)")
async def get_period(
    start: datetime = Query(..., description="Start, ISO 8601; prefer a trailing Z"),
    end: datetime | None = Query(None, description="End; defaults to now"),
    database: Database = Depends(get_database),
) -> PeriodResponse:
    start = as_utc(start)
    end = as_utc(end) if end is not None else datetime.now(timezone.utc)
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")
    if end - start > _MAX_PERIOD:
        raise HTTPException(status_code=400, detail="a period is limited to 48 hours; use /api/summary or /api/openclaw for longer")

    rows = await database.fetch_minute_aggregates(start, end)

    def extreme(field: str, pick: Literal["min", "max"], digits: int) -> PeriodExtreme:
        candidates = [row for row in rows if row[field] is not None]
        if not candidates:
            return PeriodExtreme()
        chosen = (min if pick == "min" else max)(candidates, key=lambda row: row[field])
        return PeriodExtreme(value=round(chosen[field], digits), at=_parse_stamp(chosen["bucket"]))

    return PeriodResponse(
        start=start,
        end=end,
        has_data=bool(rows),
        temperature_c_min=extreme("temperature_c_min", "min", 1),
        temperature_c_max=extreme("temperature_c_max", "max", 1),
        wind_gust_max_km_h=extreme("wind_max_km_h", "max", 1),
        # Counted from the last reading before the period, so rain that fell
        # while the station was offline is credited to the period its next
        # reading is in.
        rain_mm=await _rain_between(database, start, end, carry_in=True),
    )


_records_cache: dict[int, tuple[float, RecordsResponse]] = {}


@router.get("/records", response_model=RecordsResponse, summary="All-time extremes since the station started recording")
async def get_records(
    utc_offset_minutes: int = Query(0, ge=-840, le=840, description="Where a day starts, minutes east of UTC"),
    database: Database = Depends(get_database),
) -> RecordsResponse:
    cached = _records_cache.get(utc_offset_minutes)
    if cached is not None and time.monotonic() - cached[0] < _RECORDS_TTL_SECONDS:
        return cached[1]

    # These scan the whole history, so the answer is kept for a few minutes.
    first = await database.fetch_first_reading_timestamp()
    now = datetime.now(timezone.utc)
    hottest = await database.fetch_extreme("temperature_c", "MAX")
    coldest = await database.fetch_extreme("temperature_c", "MIN")
    gust = await database.fetch_extreme("wind_max_km_h", "MAX")

    wettest_mm: float | None = None
    wettest_day: str | None = None
    month_mm: float | None = None
    total_mm: float | None = None
    if first is not None:
        days = await database.fetch_rain_buckets(_parse_stamp(first), now, daily=True, utc_offset_minutes=utc_offset_minutes)
        rain = bucket_rain(days)
        known = [(value, row["bucket"]) for row, value in zip(days, rain) if value is not None]
        if known:
            wettest_mm, wettest_day = max(known, key=lambda item: item[0])
            this_month = (now + timedelta(minutes=utc_offset_minutes)).strftime("%Y-%m")
            month_mm = round(sum(value for value, day in known if day.startswith(this_month)), 1)
            total_mm = round(sum(value for value, _ in known), 1)

    def record(row, digits: int) -> PeriodExtreme:
        if row["value"] is None:
            return PeriodExtreme()
        return PeriodExtreme(value=round(row["value"], digits), at=_parse_stamp(row["timestamp"]))

    response = RecordsResponse(
        tracking_started_at=None if first is None else _parse_stamp(first),
        readings=await database.count_readings(),
        hottest=record(hottest, 1),
        coldest=record(coldest, 1),
        strongest_gust=record(gust, 1),
        wettest_day_mm=wettest_mm,
        wettest_day=wettest_day,
        rain_this_month_mm=month_mm,
        rain_total_mm=total_mm,
    )
    _records_cache[utc_offset_minutes] = (time.monotonic(), response)
    return response


@router.get("/station-health", response_model=StationHealthResponse, summary="How reliably readings have been arriving")
async def get_station_health(
    hours: int = Query(48, ge=6, le=168),
    database: Database = Depends(get_database),
    manager: RTL433Manager = Depends(get_ingestion_manager),
) -> StationHealthResponse:
    now = datetime.now(timezone.utc)
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    counts = {row["hour"]: row["readings"] for row in await database.fetch_hourly_counts(week_start, now)}
    stamp = "%Y-%m-%dT%H:00:00Z"
    complete_hours = [count for hour, count in counts.items() if hour != this_hour.strftime(stamp)]
    # What a normal hour looks like, from hours that had any readings at all
    # (so a long outage doesn't drag the expectation down with it).
    expected = float(statistics.median(count for count in complete_hours if count > 0)) if any(complete_hours) else None

    shown: list[HealthHour] = []
    for offset in range(hours - 1, -1, -1):
        hour = this_hour - timedelta(hours=offset)
        shown.append(
            HealthHour(hour=hour, readings=counts.get(hour.strftime(stamp), 0), partial=hour == this_hour)
        )

    complete_shown = [entry for entry in shown if not entry.partial]
    completeness: float | None = None
    if expected and complete_shown:
        completeness = round(min(100.0, 100.0 * sum(entry.readings for entry in complete_shown) / (expected * len(complete_shown))), 1)

    gap = await database.fetch_longest_gap(now - timedelta(hours=24), now)
    latest = await database.fetch_latest()
    battery: bool | None = None
    age: float | None = None
    if latest is not None:
        battery_raw = json.loads(latest["decoded_data"]).get("battery_ok")
        battery = None if battery_raw is None else bool(battery_raw)
        age = round((now - _parse_stamp(latest["timestamp"])).total_seconds())
    counts_7d = await database.fetch_health_counts(week_start, now)

    return StationHealthResponse(
        hours=shown,
        expected_per_hour=expected,
        completeness_percent=completeness,
        longest_gap_seconds=None if gap["gap_seconds"] is None else round(gap["gap_seconds"]),
        longest_gap_ended_at=None if gap["ended_at"] is None or gap["gap_seconds"] is None else _parse_stamp(gap["ended_at"]),
        last_reading_age_seconds=age,
        battery_ok=battery,
        low_battery_readings_7d=int(counts_7d["low_battery"]),
        rain_glitches_held_7d=int(counts_7d["held_rain"]),
        ignored_readings_since_start=manager.state.ignored_count,
        restart_count=manager.state.restart_count,
        ingestion_status=manager.state.status.value,
    )


@router.get("/sun", response_model=SunResponse, summary="Sunrise and sunset times around a window, for shading the night")
async def get_sun(
    start: datetime = Query(..., description="Start of the window, ISO 8601; prefer a trailing Z"),
    end: datetime = Query(..., description="End of the window"),
    settings: Settings = Depends(get_settings),
) -> SunResponse:
    start, end = as_utc(start), as_utc(end)
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")
    if end - start > _MAX_SUN_SPAN:
        raise HTTPException(status_code=400, detail="the window is limited to 400 days")
    if settings.latitude is None or settings.longitude is None:
        return SunResponse(configured=False, events=[])
    events = sun_events(settings.latitude, settings.longitude, start, end)
    return SunResponse(configured=True, events=[SunEvent(time=moment, kind=kind) for moment, kind in events])
