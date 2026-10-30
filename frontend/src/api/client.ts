import type {
  HistoryResponse,
  IngestionStatusResponse,
  LatestReading,
  NowResponse,
  PeriodResponse,
  RainBarsResponse,
  RangeKey,
  RecordsResponse,
  StationHealthResponse,
  SunResponse,
  WindowSummary,
  WindRoseResponse,
} from "../types";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchLatest(): Promise<LatestReading> {
  return request<LatestReading>("/api/latest");
}

export function fetchStatus(): Promise<IngestionStatusResponse> {
  return request<IngestionStatusResponse>("/api/status");
}

export function fetchSummary(hours = 24): Promise<WindowSummary> {
  return request<WindowSummary>(`/api/summary?hours=${hours}`);
}

export function fetchHistory(range: RangeKey, start?: Date, end?: Date): Promise<HistoryResponse> {
  const params = new URLSearchParams({ range });
  if (range === "custom" && start && end) {
    params.set("start", start.toISOString());
    params.set("end", end.toISOString());
  }
  return request<HistoryResponse>(`/api/history?${params.toString()}`);
}

export function buildExportUrl(start: Date, end: Date): string {
  const params = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return `/api/export?${params.toString()}`;
}

export function fetchNow(): Promise<NowResponse> {
  return request<NowResponse>("/api/now");
}

export function fetchRainBars(hours: number, bucket: "hour" | "day", utcOffsetMinutes: number): Promise<RainBarsResponse> {
  const params = new URLSearchParams({ hours: String(hours), bucket, utc_offset_minutes: String(utcOffsetMinutes) });
  return request<RainBarsResponse>(`/api/rain-bars?${params.toString()}`);
}

export function fetchWindRose(hours: number): Promise<WindRoseResponse> {
  return request<WindRoseResponse>(`/api/wind-rose?hours=${hours}`);
}

export function fetchPeriod(start: Date, end?: Date): Promise<PeriodResponse> {
  const params = new URLSearchParams({ start: start.toISOString() });
  if (end) {
    params.set("end", end.toISOString());
  }
  return request<PeriodResponse>(`/api/period?${params.toString()}`);
}

export function fetchRecords(utcOffsetMinutes: number): Promise<RecordsResponse> {
  return request<RecordsResponse>(`/api/records?utc_offset_minutes=${utcOffsetMinutes}`);
}

export function fetchStationHealth(hours = 48): Promise<StationHealthResponse> {
  return request<StationHealthResponse>(`/api/station-health?hours=${hours}`);
}

export function fetchSun(start: Date, end: Date): Promise<SunResponse> {
  const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
  return request<SunResponse>(`/api/sun?${params.toString()}`);
}
