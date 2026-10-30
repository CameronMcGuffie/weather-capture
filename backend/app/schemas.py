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


class WindowSummary(BaseModel):
    start: datetime
    end: datetime
    temperature_c_min: float | None = None
    temperature_c_max: float | None = None
    rain_mm: float | None = None


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
    wind_compass: str | None = None
    feels_like_c: float | None = None
    dew_point_c: float | None = None
    rain_last_hour_mm: float | None = None
    rain_24h_mm: float | None = None
    reading_age_seconds: int | None = None


class Stat(BaseModel):
    min: float | None = None
    max: float | None = None
    avg: float | None = None


class OpenClawStation(BaseModel):
    model: str | None
    sensor_id: str | None
    battery_ok: bool | None
    ingestion_status: Literal["starting", "running", "restarting", "stopped"]
    is_stale: bool
    last_reading_at: datetime | None
    reading_age_seconds: float | None


class OpenClawCurrent(BaseModel):
    observed_at: datetime
    temperature_c: float | None
    humidity: float | None
    wind_avg_km_h: float | None
    wind_gust_km_h: float | None
    wind_from_deg: float | None
    wind_from: str | None
    feels_like_c: float | None
    dew_point_c: float | None
    rain_since_tracking_began_mm: float | None
    uv: float | None
    uvi: float | None
    light_lux: float | None


class OpenClawWindow(BaseModel):
    window: str
    hours: int
    start: datetime
    end: datetime
    readings: int
    temperature_c: Stat
    humidity: Stat
    wind_avg_km_h: Stat
    wind_gust_max_km_h: float | None
    wind_from_deg: float | None
    wind_from: str | None
    rain_mm: float | None


class OpenClawSnapshot(BaseModel):
    generated_at: datetime
    station: OpenClawStation
    current: OpenClawCurrent | None
    windows: list[OpenClawWindow]
    units: dict[str, str]
    notes: list[str]


class SeriesPoint(BaseModel):
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
    wind_gust_km_h: float | None = None
    wind_from_deg: float | None = None
    wind_from: str | None = None
    rain_mm: float | None = None


class OpenClawSeries(BaseModel):
    start: datetime
    end: datetime
    resolution: Literal["minute", "hourly", "daily"]
    timestamp_meaning: str
    point_count: int
    units: dict[str, str]
    points: list[SeriesPoint]


class Trend(BaseModel):
    hours: int
    temperature_c: float | None
    humidity: float | None


class RainNow(BaseModel):
    raining: bool
    last_15_min_mm: float | None
    last_hour_mm: float | None
    last_rain_at: datetime | None


class NowResponse(BaseModel):
    observed_at: datetime
    feels_like_c: float | None
    dew_point_c: float | None
    trend: Trend
    rain: RainNow


class RainBar(BaseModel):
    timestamp: str
    rain_mm: float | None


class RainBarsResponse(BaseModel):
    start: datetime
    end: datetime
    bucket: Literal["hour", "day"]
    total_mm: float
    points: list[RainBar]


class WindBin(BaseModel):
    label: str
    min_km_h: float
    max_km_h: float | None


class WindSector(BaseModel):
    direction: str
    degrees: float
    counts: list[int]
    percent: float


class WindRoseResponse(BaseModel):
    hours: int
    readings: int
    calm_percent: float
    max_sector_percent: float
    bins: list[WindBin]
    sectors: list[WindSector]


class PeriodExtreme(BaseModel):
    value: float | None = None
    at: datetime | None = None


class PeriodResponse(BaseModel):
    start: datetime
    end: datetime
    has_data: bool
    temperature_c_min: PeriodExtreme
    temperature_c_max: PeriodExtreme
    wind_gust_max_km_h: PeriodExtreme
    rain_mm: float | None


class RecordsResponse(BaseModel):
    tracking_started_at: datetime | None
    readings: int
    hottest: PeriodExtreme
    coldest: PeriodExtreme
    strongest_gust: PeriodExtreme
    wettest_day_mm: float | None
    wettest_day: str | None
    rain_this_month_mm: float | None
    rain_total_mm: float | None


class HealthHour(BaseModel):
    hour: datetime
    readings: int
    partial: bool


class StationHealthResponse(BaseModel):
    hours: list[HealthHour]
    expected_per_hour: float | None
    completeness_percent: float | None
    longest_gap_seconds: float | None
    longest_gap_ended_at: datetime | None
    last_reading_age_seconds: float | None
    battery_ok: bool | None
    low_battery_readings_7d: int
    rain_glitches_held_7d: int
    ignored_readings_since_start: int
    restart_count: int
    ingestion_status: Literal["starting", "running", "restarting", "stopped"]


class SunEvent(BaseModel):
    time: datetime
    kind: Literal["sunrise", "sunset"]


class SunResponse(BaseModel):
    configured: bool
    events: list[SunEvent]
