import type { HistoryResponse, IngestionStatusResponse, LatestReading, RangeKey } from "../types";

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
