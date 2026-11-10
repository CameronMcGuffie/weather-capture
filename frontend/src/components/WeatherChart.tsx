import { ChevronLeft, ChevronRight, Moon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchHistory, fetchSun } from "../api/client";
import { niceTicks, nightSpans, tickLabel, withGapBreaks } from "../chartTime";
import { localDateInputValue } from "../dates";
import type { HistoryPoint, RangeKey, SunEvent } from "../types";

type MetricKey = "temperature_c" | "humidity" | "wind_avg_km_h" | "rain_mm";

interface MetricConfig {
  key: MetricKey;
  label: string;
  unit: string;
  color: string;
  digits: number;
  minKey?: keyof HistoryPoint;
  maxKey?: keyof HistoryPoint;
}

// Rain has no min/max band: it's a cumulative total, so a bucket's min/max
// are just its start and end values; the window summary shows the
// accumulated amount instead.
const METRICS: MetricConfig[] = [
  {
    key: "temperature_c",
    label: "Temperature",
    unit: "°C",
    color: "#f97316",
    digits: 1,
    minKey: "temperature_c_min",
    maxKey: "temperature_c_max",
  },
  {
    key: "humidity",
    label: "Humidity",
    unit: "%",
    color: "#38bdf8",
    digits: 0,
    minKey: "humidity_min",
    maxKey: "humidity_max",
  },
  {
    key: "wind_avg_km_h",
    label: "Wind avg",
    unit: "km/h",
    color: "#a3e635",
    digits: 1,
    minKey: "wind_avg_km_h_min",
    maxKey: "wind_avg_km_h_max",
  },
  { key: "rain_mm", label: "Rain", unit: "mm", color: "#818cf8", digits: 1 },
];

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "12h", label: "12h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "custom", label: "Custom" },
];

const RANGE_HOURS: Record<Exclude<RangeKey, "custom">, number> = {
  "1h": 1,
  "12h": 12,
  "24h": 24,
  "7d": 168,
  "30d": 720,
};

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
const COMPARE_SLOTS = 168;

interface CompareData {
  current: HistoryPoint[];
  previous: HistoryPoint[];
  currentStartMs: number;
  previousStartMs: number;
}

interface ChartRow {
  t: number;
  value?: number | null;
  range?: [number, number] | null;
  current?: number | null;
  previous?: number | null;
}

function bucketByHour(points: HistoryPoint[], startMs: number, metric: MetricKey): (number | null)[] {
  // The two compared weeks must line up by time-of-week, not by array
  // index — a gap in one week's data would otherwise shift everything
  // after it and compare mismatched hours.
  const slots: (number | null)[] = new Array(COMPARE_SLOTS).fill(null);
  for (const point of points) {
    const index = Math.floor((Date.parse(point.timestamp) - startMs) / HOUR_MS);
    if (index >= 0 && index < COMPARE_SLOTS) {
      slots[index] = point[metric];
    }
  }
  return slots;
}

export function WeatherChart() {
  const [range, setRange] = useState<RangeKey>("24h");
  const [metric, setMetric] = useState<MetricKey>("temperature_c");
  const [compareWeeks, setCompareWeeks] = useState(false);
  const [offsetHours, setOffsetHours] = useState(0);
  const [customStart, setCustomStart] = useState(localDateInputValue(2));
  const [customEnd, setCustomEnd] = useState(localDateInputValue(0));

  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [viewWindow, setViewWindow] = useState<{ start: number; end: number } | null>(null);
  const [resolution, setResolution] = useState<"minute" | "hourly">("minute");
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [sunEvents, setSunEvents] = useState<SunEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  const metricConfig = METRICS.find((entry) => entry.key === metric)!;

  const selectRange = (key: RangeKey) => {
    setRange(key);
    setOffsetHours(0);
  };

  const toggleCompare = (enabled: boolean) => {
    setCompareWeeks(enabled);
    setOffsetHours(0);
  };

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        if (compareWeeks) {
          const nowMs = Date.now();
          const currentStartMs = nowMs - COMPARE_SLOTS * HOUR_MS;
          const previousStartMs = nowMs - 2 * COMPARE_SLOTS * HOUR_MS;

          const [current, previous] = await Promise.all([
            fetchHistory("custom", new Date(currentStartMs), new Date(nowMs)),
            fetchHistory("custom", new Date(previousStartMs), new Date(currentStartMs)),
          ]);
          if (!cancelled) {
            setCompareData({
              current: current.points,
              previous: previous.points,
              currentStartMs,
              previousStartMs,
            });
            setViewWindow({ start: currentStartMs, end: nowMs });
            setResolution("hourly");
            setError(null);
            setHasLoaded(true);
          }
          return;
        }

        let response;
        if (range === "custom") {
          // No trailing Z: the picked days are the user's local days, not UTC.
          const start = new Date(`${customStart}T00:00:00`);
          const end = new Date(`${customEnd}T23:59:59`);
          if (!(start < end)) {
            if (!cancelled) {
              setError("The start date must be before the end date");
            }
            return;
          }
          response = await fetchHistory("custom", start, end);
        } else if (offsetHours > 0) {
          const end = new Date(Date.now() - offsetHours * HOUR_MS);
          const start = new Date(end.getTime() - RANGE_HOURS[range] * HOUR_MS);
          response = await fetchHistory("custom", start, end);
        } else {
          response = await fetchHistory(range);
        }

        if (!cancelled) {
          setPoints(response.points);
          setViewWindow({ start: Date.parse(response.start), end: Date.parse(response.end) });
          setResolution(response.resolution);
          setError(null);
          setHasLoaded(true);
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
  }, [range, compareWeeks, offsetHours, customStart, customEnd]);

  // Sunrise and sunset for the visible window. Asked for in whole hours so the
  // minute-by-minute refresh of a "last 24 hours" view doesn't refetch them.
  const sunFrom = viewWindow ? Math.floor(viewWindow.start / HOUR_MS) : null;
  const sunTo = viewWindow ? Math.ceil(viewWindow.end / HOUR_MS) : null;
  useEffect(() => {
    if (sunFrom === null || sunTo === null || compareWeeks) {
      return;
    }
    let cancelled = false;
    fetchSun(new Date(sunFrom * HOUR_MS), new Date(sunTo * HOUR_MS))
      .then((response) => {
        if (!cancelled) {
          setSunEvents(response.configured ? response.events : null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSunEvents(null); // shading is a nicety; the chart works without it
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sunFrom, sunTo, compareWeeks]);

  const chartData = useMemo<ChartRow[]>(() => {
    if (compareWeeks && compareData) {
      const current = bucketByHour(compareData.current, compareData.currentStartMs, metric);
      const previous = bucketByHour(compareData.previous, compareData.previousStartMs, metric);
      return Array.from({ length: COMPARE_SLOTS }, (_, index) => ({
        t: compareData.currentStartMs + index * HOUR_MS,
        current: current[index],
        previous: previous[index],
      }));
    }

    const rows = points.map((point) => {
      const min = metricConfig.minKey ? (point[metricConfig.minKey] as number | null) : null;
      const max = metricConfig.maxKey ? (point[metricConfig.maxKey] as number | null) : null;
      return {
        t: Date.parse(point.timestamp),
        value: point[metric],
        range: min !== null && max !== null ? ([min, max] as [number, number]) : null,
      };
    });
    return withGapBreaks(rows, resolution === "minute" ? MINUTE_MS : HOUR_MS);
  }, [compareWeeks, compareData, points, resolution, metric, metricConfig]);

  const hasData = useMemo(
    () =>
      chartData.some((entry) =>
        compareWeeks
          ? ("current" in entry && entry.current != null) || ("previous" in entry && entry.previous != null)
          : "value" in entry && entry.value != null,
      ),
    [chartData, compareWeeks],
  );

  const summary = useMemo(() => {
    if (compareWeeks) {
      return null;
    }
    const values = points.map((point) => point[metric]).filter((value): value is number => value !== null);
    if (values.length === 0) {
      return null;
    }

    if (metric === "rain_mm") {
      // Rain is cumulative and the server counts it from zero at the start
      // of the window, so the amount that fell is simply how high it got.
      // (Subtracting the first value would drop rain already in it: what
      // fell in the first bucket, or while the station was offline.)
      return { kind: "rain" as const, total: Math.max(...values) };
    }

    const lows = points
      .map((point) => (metricConfig.minKey ? (point[metricConfig.minKey] as number | null) : null) ?? point[metric])
      .filter((value): value is number => value !== null);
    const highs = points
      .map((point) => (metricConfig.maxKey ? (point[metricConfig.maxKey] as number | null) : null) ?? point[metric])
      .filter((value): value is number => value !== null);
    return { kind: "band" as const, low: Math.min(...lows), high: Math.max(...highs) };
  }, [compareWeeks, points, metric, metricConfig]);

  const axis = useMemo(() => (viewWindow ? niceTicks(viewWindow.start, viewWindow.end) : null), [viewWindow]);
  const nights = useMemo(
    () => (!compareWeeks && sunEvents && viewWindow ? nightSpans(sunEvents, viewWindow.start, viewWindow.end) : []),
    [compareWeeks, sunEvents, viewWindow],
  );

  const formatTooltipTime = (value: number) =>
    new Date(value).toLocaleString([], {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "numeric",
      minute: resolution === "minute" && !compareWeeks ? "2-digit" : undefined,
    });

  const showTimeNav = !compareWeeks && range !== "custom";
  const showNightKey = !compareWeeks && sunEvents !== null;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-4">
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

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={compareWeeks}
              onChange={(event) => toggleCompare(event.target.checked)}
              className="rounded border-slate-600 bg-slate-800"
            />
            Compare vs last week
          </label>

          {!compareWeeks && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-wrap gap-1 rounded-lg bg-slate-800/60 p-1">
                {RANGES.map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    onClick={() => selectRange(entry.key)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                      range === entry.key ? "bg-accent-600 text-white" : "text-slate-400 hover:text-slate-100"
                    }`}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>

              {showTimeNav && (
                <div className="flex items-center gap-1 rounded-lg bg-slate-800/60 p-1">
                  <button
                    type="button"
                    aria-label="Back 1 hour"
                    onClick={() => setOffsetHours((hours) => hours + 1)}
                    className="rounded-md p-2 text-slate-400 transition hover:text-slate-100"
                  >
                    <ChevronLeft size={18} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setOffsetHours(0)}
                    disabled={offsetHours === 0}
                    title={offsetHours > 0 ? "Return to now" : undefined}
                    className={`min-w-12 rounded-md px-2 py-1.5 text-center text-xs font-medium transition ${
                      offsetHours > 0
                        ? "bg-accent-600 text-white hover:bg-accent-500"
                        : "cursor-default text-slate-500"
                    }`}
                  >
                    {offsetHours > 0 ? `−${offsetHours}h` : "Now"}
                  </button>
                  <button
                    type="button"
                    aria-label="Forward 1 hour"
                    disabled={offsetHours === 0}
                    onClick={() => setOffsetHours((hours) => Math.max(0, hours - 1))}
                    className="rounded-md p-2 text-slate-400 transition enabled:hover:text-slate-100 disabled:opacity-40"
                  >
                    <ChevronRight size={18} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {!compareWeeks && range === "custom" && (
        <div className="mb-4 flex flex-wrap gap-3">
          <input
            type="date"
            aria-label="Chart range start"
            value={customStart}
            onChange={(event) => setCustomStart(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
          <input
            type="date"
            aria-label="Chart range end"
            value={customEnd}
            onChange={(event) => setCustomEnd(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
        </div>
      )}

      {hasData && !error && (showNightKey || summary) && (
        <div className="mb-2 flex items-center justify-between gap-3 text-xs text-slate-400 sm:text-sm">
          <span className="flex items-center gap-1.5">
            {showNightKey ? (
              <>
                <Moon size={14} aria-hidden="true" />
                Night shaded
              </>
            ) : null}
          </span>
          {summary ? (
            <p className="text-right">
              {summary.kind === "rain" ? (
                <>
                  Total in window{" "}
                  <span className="font-medium text-slate-200">
                    {summary.total.toFixed(metricConfig.digits)} {metricConfig.unit}
                  </span>
                </>
              ) : (
                <>
                  Low{" "}
                  <span className="font-medium text-slate-200">
                    {summary.low.toFixed(metricConfig.digits)}
                    {metricConfig.unit}
                  </span>
                  {" · "}High{" "}
                  <span className="font-medium text-slate-200">
                    {summary.high.toFixed(metricConfig.digits)}
                    {metricConfig.unit}
                  </span>
                </>
              )}
            </p>
          ) : null}
        </div>
      )}

      {error ? (
        <p className="py-12 text-center text-sm text-red-400">{error}</p>
      ) : hasLoaded && !hasData ? (
        <p className="py-12 text-center text-sm text-slate-500">No data recorded in this time window</p>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            {nights.map(([from, to]) => (
              <ReferenceArea key={from} x1={from} x2={to} fill="#94a3b8" fillOpacity={0.1} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis
              type="number"
              dataKey="t"
              scale="time"
              domain={viewWindow ? [viewWindow.start, viewWindow.end] : ["dataMin", "dataMax"]}
              ticks={axis?.ticks}
              tickFormatter={(value: number) => (axis ? tickLabel(value, axis.step) : String(value))}
              allowDataOverflow
              stroke="#64748b"
              fontSize={12}
              tickMargin={8}
            />
            <YAxis stroke="#64748b" fontSize={12} unit={metricConfig.unit} width={56} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#94a3b8" }}
              labelFormatter={formatTooltipTime}
              formatter={(value: number | string | (number | string)[], name: string | number) => {
                if (Array.isArray(value)) {
                  return [`${value[0]} – ${value[1]} ${metricConfig.unit}`, "min – max"];
                }
                return [`${value} ${metricConfig.unit}`, String(name)];
              }}
            />
            {compareWeeks ? (
              <>
                <Legend />
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
              <>
                {metricConfig.minKey && (
                  <Area
                    type="monotone"
                    dataKey="range"
                    name="min – max"
                    stroke="none"
                    fill={metricConfig.color}
                    fillOpacity={0.14}
                    activeDot={false}
                    legendType="none"
                  />
                )}
                <Line
                  type="monotone"
                  dataKey="value"
                  name={metricConfig.label}
                  stroke={metricConfig.color}
                  dot={false}
                  strokeWidth={2}
                />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
