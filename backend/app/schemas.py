from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LatestReading(BaseModel):
    timestamp: datetime
    model: str | None = None
    sensor_id: str | None = None
    battery_ok: int | None = None
    temperature_c: float | None = None
    humidity: float | None = None
    wind_dir_deg: float | None = None
    wind_avg_km_h: float | None = None
    wind_max_km_h: float | None = None
    rain_mm: float | None = None
    uv: float | None = None
    uvi: float | None = None
    light_lux: float | None = None


class HistoryPoint(BaseModel):
    timestamp: str
    temperature_c: float | None = None
    temperature_c_min: float | None = None
    temperature_c_max: float | None = None
    humidity: float | None = None
    humidity_min: float | None = None
    humidity_max: float | None = None
    wind_avg_km_h: float | None = None
    wind_avg_km_h_min: float | None = None
    wind_avg_km_h_max: float | None = None
    wind_max_km_h: float | None = None
    wind_dir_deg: float | None = None
    rain_mm: float | None = None


class HistoryResponse(BaseModel):
    resolution: Literal["minute", "hourly"]
    start: datetime
    end: datetime
    points: list[HistoryPoint]


class WeekComparisonResponse(BaseModel):
    current_week: list[HistoryPoint]
    previous_week: list[HistoryPoint]


class IngestionStatusResponse(BaseModel):
    status: Literal["starting", "running", "restarting", "stopped"]
    pid: int | None
    started_at: datetime | None
    last_reading_at: datetime | None
    restart_count: int
    last_error: str | None
    is_stale: bool
    ignored_count: int


class HomeAssistantPayload(BaseModel):
    temperature_c: float | None = None
    humidity: float | None = None
    wind_dir_deg: float | None = None
    wind_avg_km_h: float | None = None
    wind_max_km_h: float | None = None
    rain_mm: float | None = None
    battery_ok: int | None = None
    updated_at: datetime | None = None
