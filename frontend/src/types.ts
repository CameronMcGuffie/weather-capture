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
  humidity: number | null;
  wind_avg_km_h: number | null;
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

export type RangeKey = "1h" | "24h" | "7d" | "30d" | "custom";
