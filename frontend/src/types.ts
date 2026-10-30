export interface LatestReading {
  timestamp: string;
  model: string | null;
  sensor_id: string | null;
  battery_ok: number | null;
  temperature_c: number | null;
  humidity: number | null;
  wind_dir_deg: number | null;
  wind_avg_km_h: number | null;
  wind_max_km_h: number | null;
  rain_mm: number | null;
  uv: number | null;
  uvi: number | null;
  light_lux: number | null;
}

export interface HistoryPoint {
  timestamp: string;
  temperature_c: number | null;
  temperature_c_min: number | null;
  temperature_c_max: number | null;
  humidity: number | null;
  humidity_min: number | null;
  humidity_max: number | null;
  wind_avg_km_h: number | null;
  wind_avg_km_h_min: number | null;
  wind_avg_km_h_max: number | null;
  wind_max_km_h: number | null;
  wind_dir_deg: number | null;
  rain_mm: number | null;
}

export interface HistoryResponse {
  resolution: "minute" | "hourly";
  start: string;
  end: string;
  points: HistoryPoint[];
}

export type IngestionStatusValue = "starting" | "running" | "restarting" | "stopped";

export interface IngestionStatusResponse {
  status: IngestionStatusValue;
  pid: number | null;
  started_at: string | null;
  last_reading_at: string | null;
  restart_count: number;
  last_error: string | null;
  is_stale: boolean;
  ignored_count: number;
}

export type RangeKey = "1h" | "12h" | "24h" | "7d" | "30d" | "custom";

export interface WindowSummary {
  start: string;
  end: string;
  temperature_c_min: number | null;
  temperature_c_max: number | null;
  rain_mm: number | null;
}

export interface Trend {
  hours: number;
  temperature_c: number | null;
  humidity: number | null;
}

export interface RainNow {
  raining: boolean;
  last_15_min_mm: number | null;
  last_hour_mm: number | null;
  last_rain_at: string | null;
}

export interface NowResponse {
  observed_at: string;
  feels_like_c: number | null;
  dew_point_c: number | null;
  trend: Trend;
  rain: RainNow;
}

export interface RainBar {
  timestamp: string;
  rain_mm: number | null;
}

export interface RainBarsResponse {
  start: string;
  end: string;
  bucket: "hour" | "day";
  total_mm: number;
  points: RainBar[];
}

export interface WindBin {
  label: string;
  min_km_h: number;
  max_km_h: number | null;
}

export interface WindSector {
  direction: string;
  degrees: number;
  counts: number[];
  percent: number;
}

export interface WindRoseResponse {
  hours: number;
  readings: number;
  calm_percent: number;
  max_sector_percent: number;
  bins: WindBin[];
  sectors: WindSector[];
}

export interface PeriodExtreme {
  value: number | null;
  at: string | null;
}

export interface PeriodResponse {
  start: string;
  end: string;
  has_data: boolean;
  temperature_c_min: PeriodExtreme;
  temperature_c_max: PeriodExtreme;
  wind_gust_max_km_h: PeriodExtreme;
  rain_mm: number | null;
}

export interface RecordsResponse {
  tracking_started_at: string | null;
  readings: number;
  hottest: PeriodExtreme;
  coldest: PeriodExtreme;
  strongest_gust: PeriodExtreme;
  wettest_day_mm: number | null;
  wettest_day: string | null;
  rain_this_month_mm: number | null;
  rain_total_mm: number | null;
}

export interface HealthHour {
  hour: string;
  readings: number;
  partial: boolean;
}

export interface StationHealthResponse {
  hours: HealthHour[];
  expected_per_hour: number | null;
  completeness_percent: number | null;
  longest_gap_seconds: number | null;
  longest_gap_ended_at: string | null;
  last_reading_age_seconds: number | null;
  battery_ok: boolean | null;
  low_battery_readings_7d: number;
  rain_glitches_held_7d: number;
  ignored_readings_since_start: number;
  restart_count: number;
  ingestion_status: IngestionStatusValue;
}

export interface SunEvent {
  time: string;
  kind: "sunrise" | "sunset";
}

export interface SunResponse {
  configured: boolean;
  events: SunEvent[];
}
