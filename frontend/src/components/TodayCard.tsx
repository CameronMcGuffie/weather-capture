import { fetchPeriod } from "../api/client";
import { formatClock, localMidnight } from "../dates";
import { usePolling } from "../hooks/usePolling";
import type { PeriodExtreme, PeriodResponse } from "../types";
import { Card } from "./Card";

function Extreme({ extreme, unit, digits = 1 }: { extreme: PeriodExtreme | undefined; unit: string; digits?: number }) {
  if (!extreme || extreme.value === null) {
    return <span className="text-slate-500">–</span>;
  }
  return (
    <span>
      <span className="font-medium text-slate-100">
        {extreme.value.toFixed(digits)}
        {unit}
      </span>
      {extreme.at ? <span className="ml-1.5 text-xs text-slate-400">{formatClock(extreme.at)}</span> : null}
    </span>
  );
}

function Rain({ period }: { period: PeriodResponse | null }) {
  if (!period || period.rain_mm === null) {
    return <span className="text-slate-500">–</span>;
  }
  return <span className="font-medium text-slate-100">{period.rain_mm.toFixed(1)} mm</span>;
}

/** Today so far, next to the whole of yesterday, in the viewer's own days. */
export function TodayCard() {
  const { data: today } = usePolling(() => fetchPeriod(localMidnight(0)), 60_000);
  const { data: yesterday } = usePolling(() => fetchPeriod(localMidnight(1), localMidnight(0)), 300_000);

  const rows: { label: string; render: (period: PeriodResponse | null) => JSX.Element }[] = [
    { label: "High", render: (period) => <Extreme extreme={period?.temperature_c_max} unit="°C" /> },
    { label: "Low", render: (period) => <Extreme extreme={period?.temperature_c_min} unit="°C" /> },
    { label: "Peak gust", render: (period) => <Extreme extreme={period?.wind_gust_max_km_h} unit=" km/h" /> },
    { label: "Rain", render: (period) => <Rain period={period} /> },
  ];

  return (
    <Card title="Today" note="Since midnight, against all of yesterday">
      <div className="grid grid-cols-[auto_1fr_1fr] gap-x-4 gap-y-2 text-sm">
        <span />
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Today</span>
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Yesterday</span>
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <span className="text-slate-400">{row.label}</span>
            <span>{row.render(today)}</span>
            <span>{row.render(yesterday)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
