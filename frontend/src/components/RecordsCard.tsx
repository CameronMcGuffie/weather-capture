import { fetchRecords } from "../api/client";
import { formatDateTime, formatLocalDate, utcOffsetMinutes } from "../dates";
import { usePolling } from "../hooks/usePolling";
import type { PeriodExtreme } from "../types";
import { Card } from "./Card";

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="truncate text-lg font-semibold text-slate-50">{value}</p>
      {detail ? <p className="truncate text-xs text-slate-400">{detail}</p> : null}
    </div>
  );
}

function extreme(record: PeriodExtreme | undefined, unit: string): { value: string; detail?: string } {
  if (!record || record.value === null) {
    return { value: "–" };
  }
  return { value: `${record.value.toFixed(1)}${unit}`, detail: record.at ? formatDateTime(record.at) : undefined };
}

function millimetres(value: number | null): string {
  return value === null ? "–" : `${value.toFixed(1)} mm`;
}

/** All-time extremes since the station started recording. */
export function RecordsCard() {
  const { data, error } = usePolling(() => fetchRecords(utcOffsetMinutes()), 600_000);

  const hottest = extreme(data?.hottest, "°C");
  const coldest = extreme(data?.coldest, "°C");
  const gust = extreme(data?.strongest_gust, " km/h");
  const since = data?.tracking_started_at
    ? new Date(data.tracking_started_at).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })
    : null;

  return (
    <Card
      title="Records"
      note={data ? (since ? `Since ${since} · ${data.readings.toLocaleString()} readings` : "No readings yet") : " "}
    >
      {error ? (
        <p className="py-6 text-center text-sm text-red-400">{error}</p>
      ) : !data ? (
        <div className="h-[170px]" aria-busy="true" />
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-4">
          <Stat label="Hottest" {...hottest} />
          <Stat label="Coldest" {...coldest} />
          <Stat label="Strongest gust" {...gust} />
          <Stat
            label="Wettest day"
            value={millimetres(data.wettest_day_mm)}
            detail={data.wettest_day ? formatLocalDate(data.wettest_day, true) : undefined}
          />
          <Stat label="Rain this month" value={millimetres(data.rain_this_month_mm)} />
          <Stat label="Rain since tracking began" value={millimetres(data.rain_total_mm)} />
        </div>
      )}
    </Card>
  );
}
