import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchHistory } from "../api/client";
import type { HistoryPoint, RangeKey } from "../types";

type MetricKey = "temperature_c" | "humidity" | "wind_avg_km_h" | "rain_mm";

const METRICS: { key: MetricKey; label: string; unit: string; color: string }[] = [
  { key: "temperature_c", label: "Temperature", unit: "°C", color: "#f97316" },
  { key: "humidity", label: "Humidity", unit: "%", color: "#38bdf8" },
  { key: "wind_avg_km_h", label: "Wind avg", unit: "km/h", color: "#a3e635" },
  { key: "rain_mm", label: "Rain", unit: "mm", color: "#818cf8" },
];

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "custom", label: "Custom" },
];

function formatTick(timestamp: string, resolution: "minute" | "hourly"): string {
  const date = new Date(timestamp);
  if (resolution === "hourly") {
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit" });
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export function WeatherChart() {
  const [range, setRange] = useState<RangeKey>("24h");
  const [metric, setMetric] = useState<MetricKey>("temperature_c");
  const [compareWeeks, setCompareWeeks] = useState(false);
  const [customStart, setCustomStart] = useState(isoDaysAgo(2));
  const [customEnd, setCustomEnd] = useState(isoDaysAgo(0));

  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [resolution, setResolution] = useState<"minute" | "hourly">("minute");
  const [comparePoints, setComparePoints] = useState<{ current: HistoryPoint[]; previous: HistoryPoint[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const metricConfig = METRICS.find((entry) => entry.key === metric)!;

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        if (compareWeeks) {
          const now = new Date();
          const currentStart = new Date(now);
          currentStart.setDate(currentStart.getDate() - 7);
          const previousStart = new Date(now);
          previousStart.setDate(previousStart.getDate() - 14);
          const previousEnd = new Date(now);
          previousEnd.setDate(previousEnd.getDate() - 7);

          const [current, previous] = await Promise.all([
            fetchHistory("custom", currentStart, now),
            fetchHistory("custom", previousStart, previousEnd),
          ]);
          if (!cancelled) {
            setComparePoints({ current: current.points, previous: previous.points });
            setResolution("hourly");
            setError(null);
          }
          return;
        }

        const start = range === "custom" ? new Date(`${customStart}T00:00:00Z`) : undefined;
        const end = range === "custom" ? new Date(`${customEnd}T23:59:59Z`) : undefined;
        const response = await fetchHistory(range, start, end);
        if (!cancelled) {
          setPoints(response.points);
          setResolution(response.resolution);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "failed to load history");
        }
      }
    };

    load();
    const id = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [range, metric, compareWeeks, customStart, customEnd]);

  const chartData = useMemo(() => {
    if (compareWeeks && comparePoints) {
      const length = Math.max(comparePoints.current.length, comparePoints.previous.length);
      return Array.from({ length }, (_, index) => ({
        label: comparePoints.current[index]
          ? formatTick(comparePoints.current[index].timestamp, "hourly")
          : `+${index}h`,
        current: comparePoints.current[index]?.[metric] ?? null,
        previous: comparePoints.previous[index]?.[metric] ?? null,
      }));
    }

    return points.map((point) => ({
      label: formatTick(point.timestamp, resolution),
      value: point[metric],
    }));
  }, [compareWeeks, comparePoints, points, resolution, metric]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-1 rounded-lg bg-slate-800/60 p-1">
          {METRICS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setMetric(entry.key)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                metric === entry.key ? "bg-accent-600 text-white" : "text-slate-400 hover:text-slate-100"
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={compareWeeks}
              onChange={(event) => setCompareWeeks(event.target.checked)}
              className="rounded border-slate-600 bg-slate-800"
            />
            Compare vs last week
          </label>

          {!compareWeeks && (
            <div className="flex gap-1 rounded-lg bg-slate-800/60 p-1">
              {RANGES.map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  onClick={() => setRange(entry.key)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    range === entry.key ? "bg-accent-600 text-white" : "text-slate-400 hover:text-slate-100"
                  }`}
                >
                  {entry.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {!compareWeeks && range === "custom" && (
        <div className="mb-4 flex flex-wrap gap-3">
          <input
            type="date"
            value={customStart}
            onChange={(event) => setCustomStart(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
          <input
            type="date"
            value={customEnd}
            onChange={(event) => setCustomEnd(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
        </div>
      )}

      {error ? (
        <p className="py-12 text-center text-sm text-red-400">{error}</p>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" stroke="#64748b" fontSize={12} tickMargin={8} minTickGap={24} />
            <YAxis stroke="#64748b" fontSize={12} unit={metricConfig.unit} width={48} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#94a3b8" }}
            />
            <Legend />
            {compareWeeks ? (
              <>
                <Line
                  type="monotone"
                  dataKey="current"
                  name="This week"
                  stroke={metricConfig.color}
                  dot={false}
                  strokeWidth={2}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="previous"
                  name="Last week"
                  stroke="#64748b"
                  strokeDasharray="4 4"
                  dot={false}
                  strokeWidth={2}
                  connectNulls
                />
              </>
            ) : (
              <Line
                type="monotone"
                dataKey="value"
                name={metricConfig.label}
                stroke={metricConfig.color}
                dot={false}
                strokeWidth={2}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
