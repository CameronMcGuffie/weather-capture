import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchRainBars } from "../api/client";
import { formatLocalDate, utcOffsetMinutes } from "../dates";
import { usePolling } from "../hooks/usePolling";
import { Card } from "./Card";
import { Segmented } from "./Segmented";

const PERIODS = {
  "24h": { label: "24 h", hours: 24, bucket: "hour" as const, caption: "in the last 24 hours" },
  "7d": { label: "7 days", hours: 24 * 7, bucket: "day" as const, caption: "in the last 7 days" },
  "30d": { label: "30 days", hours: 24 * 30, bucket: "day" as const, caption: "in the last 30 days" },
};
type PeriodKey = keyof typeof PERIODS;

const OPTIONS = (Object.keys(PERIODS) as PeriodKey[]).map((key) => ({ key, label: PERIODS[key].label }));

/** Every hour or day from the first to the last timestamp, in the same format the API uses. */
function bucketSlots(stamps: string[], bucket: "hour" | "day"): string[] {
  if (stamps.length === 0) {
    return [];
  }
  const sorted = [...stamps].sort();
  const step = bucket === "hour" ? 3_600_000 : 86_400_000;
  const first = new Date(sorted[0]).getTime();
  const last = new Date(sorted[sorted.length - 1]).getTime();
  const slots: string[] = [];
  for (let at = first; at <= last; at += step) {
    const iso = new Date(at).toISOString();
    slots.push(bucket === "hour" ? `${iso.slice(0, 13)}:00:00Z` : iso.slice(0, 10));
  }
  return slots;
}

/** Rain that fell in each hour or day: bars say more than a cumulative line. */
export function RainBars() {
  const [period, setPeriod] = useState<PeriodKey>("24h");
  const { hours, bucket, caption } = PERIODS[period];
  const { data, error } = usePolling(() => fetchRainBars(hours, bucket, utcOffsetMinutes()), 60_000, [period]);

  // The API leaves out buckets with no readings (an outage); put them back as empty slots so the axis stays honest.
  const points = new Map((data?.points ?? []).map((point) => [point.timestamp, point.rain_mm ?? 0]));
  const bars = bucketSlots(Array.from(points.keys()), bucket).map((slot) => {
    const rain = points.get(slot) ?? 0;
    if (bucket === "hour") {
      const at = new Date(slot);
      return {
        label: at.toLocaleTimeString([], { hour: "numeric" }),
        full: at.toLocaleString([], { weekday: "short", hour: "numeric" }),
        rain,
      };
    }
    return {
      label: formatLocalDate(slot),
      full: new Date(`${slot}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }),
      rain,
    };
  });

  // Label every Nth bar so about six labels are shown, evenly spaced, at any width.
  const labelEvery = Math.max(1, Math.ceil(bars.length / 6));

  return (
    <Card
      title="Rain"
      note={data ? `${data.total_mm.toFixed(1)} mm ${caption}` : " "}
      actions={<Segmented label="Rain period" options={OPTIONS} value={period} onChange={setPeriod} />}
    >
      {error ? (
        <p className="py-10 text-center text-sm text-red-400">{error}</p>
      ) : !data ? (
        <div className="h-[200px]" aria-busy="true" />
      ) : data.total_mm === 0 ? (
        <p className="flex h-[200px] items-center justify-center text-sm text-slate-500">No rain {caption}</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={bars} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" stroke="#64748b" fontSize={12} tickMargin={6} interval={labelEvery - 1} />
            <YAxis
              stroke="#64748b"
              fontSize={12}
              width={56}
              unit=" mm"
              allowDecimals
              domain={[0, (dataMax: number) => Math.max(1, Math.ceil(dataMax * 1.1))]}
            />
            <Tooltip
              cursor={{ fill: "#1e293b" }}
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#94a3b8" }}
              labelFormatter={(_, payload) => payload?.[0]?.payload?.full ?? ""}
              formatter={(value: number) => [`${value.toFixed(1)} mm`, "Rain"]}
            />
            <Bar dataKey="rain" fill="#818cf8" radius={[3, 3, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
