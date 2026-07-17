from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.database import Database
from app.dependencies import get_database
from app.schemas import HistoryPoint, HistoryResponse, HomeAssistantPayload, LatestReading, WindowSummary

router = APIRouter(prefix="/api", tags=["weather"])

_RANGE_SPANS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

_CANONICAL_FIELDS = (
    "temperature_c",
    "humidity",
    "wind_dir_deg",
    "wind_avg_km_h",
    "wind_max_km_h",
    "rain_mm",
)


def _resolve_span(
    range_key: Literal["1h", "12h", "24h", "7d", "30d", "custom"],
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    if range_key == "custom":
        if start is None or end is None:
            raise HTTPException(status_code=400, detail="start and end are required for a custom range")
        if start >= end:
            raise HTTPException(status_code=400, detail="start must be before end")
        return start, end

    resolved_end = datetime.now(timezone.utc)
    return resolved_end - _RANGE_SPANS[range_key], resolved_end


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _adjust_rain(value: float | None, baseline: float | None) -> float | None:
    """Shift the reset-aware rain total to be relative to the first-ever
    recorded value, clamped so float noise can't show it going negative.
    """
    if value is None or baseline is None:
        return value
    return max(value - baseline, 0.0)


def _rain_total(decoded: dict[str, Any]) -> float | None:
    """rain_total_mm is the reset-aware running total (see RTL433Manager);
    readings stored before that field existed fall back to the sensor's raw
    cumulative value, which is equivalent since no reset had happened yet.
    """
    total = decoded.get("rain_total_mm")
    return total if total is not None else decoded.get("rain_mm")


def _build_history_point(row: aiosqlite.Row, rain_baseline: float | None) -> HistoryPoint:
    return HistoryPoint(
        timestamp=row["bucket"],
        temperature_c=_round(row["temperature_c"], 1),
        temperature_c_min=_round(row["temperature_c_min"], 1),
        temperature_c_max=_round(row["temperature_c_max"], 1),
        humidity=_round(row["humidity"], 0),
        humidity_min=_round(row["humidity_min"], 0),
        humidity_max=_round(row["humidity_max"], 0),
        wind_avg_km_h=_round(row["wind_avg_km_h"], 1),
        wind_avg_km_h_min=_round(row["wind_avg_km_h_min"], 1),
        wind_avg_km_h_max=_round(row["wind_avg_km_h_max"], 1),
        wind_max_km_h=_round(row["wind_max_km_h"], 1),
        wind_dir_deg=_round(row["wind_dir_deg"], 0),
        rain_mm=_round(_adjust_rain(row["rain_mm"], rain_baseline), 2),
    )


@router.get("/latest", response_model=LatestReading)
async def get_latest(database: Database = Depends(get_database)) -> LatestReading:
    row = await database.fetch_latest()
    if row is None:
        raise HTTPException(status_code=404, detail="no readings recorded yet")

    decoded = json.loads(row["decoded_data"])
    rain_baseline = await database.fetch_rain_baseline_mm()
    return LatestReading(
        timestamp=row["timestamp"],
        model=decoded.get("model"),
        sensor_id=str(decoded.get("id")) if decoded.get("id") is not None else None,
        battery_ok=decoded.get("battery_ok"),
        temperature_c=decoded.get("temperature_c"),
        humidity=decoded.get("humidity"),
        wind_dir_deg=decoded.get("wind_dir_deg"),
        wind_avg_km_h=decoded.get("wind_avg_km_h"),
        wind_max_km_h=decoded.get("wind_max_km_h"),
        rain_mm=_round(_adjust_rain(_rain_total(decoded), rain_baseline), 2),
        uv=decoded.get("uv"),
        uvi=decoded.get("uvi"),
        light_lux=decoded.get("light_lux"),
    )


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    range: Literal["1h", "12h", "24h", "7d", "30d", "custom"] = Query("24h"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    database: Database = Depends(get_database),
) -> HistoryResponse:
    span_start, span_end = _resolve_span(range, start, end)

    if span_end - span_start > timedelta(hours=24):
        rows = await database.fetch_hourly_aggregates(span_start, span_end)
        resolution: Literal["minute", "hourly"] = "hourly"
    else:
        # The sensor transmits far more than once a minute, so even the
        # finest-grained view is aggregated rather than plotting every raw
        # reading (which would otherwise be noisy and needlessly dense).
        rows = await database.fetch_minute_aggregates(span_start, span_end)
        resolution = "minute"

    # Rain is re-based to the first value inside the window, so the chart
    # shows rain that fell during the displayed period (starting from 0)
    # rather than a lifetime total that old rain keeps propping up forever.
    rain_baseline = next((row["rain_mm"] for row in rows if row["rain_mm"] is not None), None)

    points = [_build_history_point(row, rain_baseline) for row in rows]
    return HistoryResponse(resolution=resolution, start=span_start, end=span_end, points=points)


@router.get("/summary", response_model=WindowSummary)
async def get_window_summary(
    hours: int = Query(24, ge=1, le=720),
    database: Database = Depends(get_database),
) -> WindowSummary:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    row = await database.fetch_window_summary(start, end)

    rain_mm: float | None = None
    if row["rain_first_mm"] is not None and row["rain_last_mm"] is not None:
        # The reset-aware total only ever climbs, so last minus first is the
        # rain that fell inside the window.
        rain_mm = _round(row["rain_last_mm"] - row["rain_first_mm"], 2)

    return WindowSummary(
        start=start,
        end=end,
        temperature_c_min=_round(row["temperature_c_min"], 1),
        temperature_c_max=_round(row["temperature_c_max"], 1),
        rain_mm=rain_mm,
    )


@router.get("/export")
async def export_csv(
    start: datetime = Query(...),
    end: datetime = Query(...),
    database: Database = Depends(get_database),
) -> StreamingResponse:
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    rows = await database.fetch_raw_range(start, end)
    rain_baseline = await database.fetch_rain_baseline_mm()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("timestamp", *_CANONICAL_FIELDS))
    rain_index = _CANONICAL_FIELDS.index("rain_mm")
    for row in rows:
        decoded = json.loads(row["decoded_data"])
        values = [decoded.get(field) for field in _CANONICAL_FIELDS]
        values[rain_index] = _round(_adjust_rain(_rain_total(decoded), rain_baseline), 2)
        writer.writerow((row["timestamp"], *values))
    buffer.seek(0)

    filename = f"weather-{start.date().isoformat()}-{end.date().isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ha", response_model=HomeAssistantPayload)
async def get_home_assistant_payload(database: Database = Depends(get_database)) -> HomeAssistantPayload:
    row = await database.fetch_latest()
    if row is None:
        return HomeAssistantPayload()

    decoded = json.loads(row["decoded_data"])
    rain_baseline = await database.fetch_rain_baseline_mm()
    return HomeAssistantPayload(
        temperature_c=decoded.get("temperature_c"),
        humidity=decoded.get("humidity"),
        wind_dir_deg=decoded.get("wind_dir_deg"),
        wind_avg_km_h=decoded.get("wind_avg_km_h"),
        wind_max_km_h=decoded.get("wind_max_km_h"),
        rain_mm=_round(_adjust_rain(_rain_total(decoded), rain_baseline), 2),
        battery_ok=decoded.get("battery_ok"),
        updated_at=row["timestamp"],
    )
