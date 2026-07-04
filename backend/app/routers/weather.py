from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.database import Database
from app.dependencies import get_database
from app.schemas import HistoryPoint, HistoryResponse, HomeAssistantPayload, LatestReading

router = APIRouter(prefix="/api", tags=["weather"])

_RANGE_SPANS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
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
    range_key: Literal["1h", "24h", "7d", "30d", "custom"],
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


@router.get("/latest", response_model=LatestReading)
async def get_latest(database: Database = Depends(get_database)) -> LatestReading:
    row = await database.fetch_latest()
    if row is None:
        raise HTTPException(status_code=404, detail="no readings recorded yet")

    decoded = json.loads(row["decoded_data"])
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
        rain_mm=decoded.get("rain_mm"),
        uv=decoded.get("uv"),
        uvi=decoded.get("uvi"),
        light_lux=decoded.get("light_lux"),
    )


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    range: Literal["1h", "24h", "7d", "30d", "custom"] = Query("24h"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    database: Database = Depends(get_database),
) -> HistoryResponse:
    span_start, span_end = _resolve_span(range, start, end)

    if span_end - span_start > timedelta(hours=24):
        rows = await database.fetch_hourly_aggregates(span_start, span_end)
        points = [
            HistoryPoint(
                timestamp=row["bucket"],
                temperature_c=row["temperature_c"],
                humidity=row["humidity"],
                wind_avg_km_h=row["wind_avg_km_h"],
                wind_max_km_h=row["wind_max_km_h"],
                wind_dir_deg=row["wind_dir_deg"],
                rain_mm=row["rain_mm"],
            )
            for row in rows
        ]
        resolution: Literal["raw", "hourly"] = "hourly"
    else:
        rows = await database.fetch_raw_range(span_start, span_end)
        points = []
        for row in rows:
            decoded = json.loads(row["decoded_data"])
            points.append(
                HistoryPoint(
                    timestamp=row["timestamp"],
                    temperature_c=decoded.get("temperature_c"),
                    humidity=decoded.get("humidity"),
                    wind_avg_km_h=decoded.get("wind_avg_km_h"),
                    wind_max_km_h=decoded.get("wind_max_km_h"),
                    wind_dir_deg=decoded.get("wind_dir_deg"),
                    rain_mm=decoded.get("rain_mm"),
                )
            )
        resolution = "raw"

    return HistoryResponse(resolution=resolution, start=span_start, end=span_end, points=points)


@router.get("/export")
async def export_csv(
    start: datetime = Query(...),
    end: datetime = Query(...),
    database: Database = Depends(get_database),
) -> StreamingResponse:
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    rows = await database.fetch_raw_range(start, end)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("timestamp", *_CANONICAL_FIELDS))
    for row in rows:
        decoded = json.loads(row["decoded_data"])
        writer.writerow((row["timestamp"], *(decoded.get(field) for field in _CANONICAL_FIELDS)))
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
    return HomeAssistantPayload(
        temperature_c=decoded.get("temperature_c"),
        humidity=decoded.get("humidity"),
        wind_dir_deg=decoded.get("wind_dir_deg"),
        wind_avg_km_h=decoded.get("wind_avg_km_h"),
        wind_max_km_h=decoded.get("wind_max_km_h"),
        rain_mm=decoded.get("rain_mm"),
        battery_ok=decoded.get("battery_ok"),
        updated_at=row["timestamp"],
    )
