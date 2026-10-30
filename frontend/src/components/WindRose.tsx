import { useState } from "react";

import { fetchWindRose } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { WindRoseResponse } from "../types";
import { Card } from "./Card";
import { Segmented } from "./Segmented";

const PERIODS = { "7d": 24 * 7, "30d": 24 * 30, "90d": 24 * 90 };
type PeriodKey = keyof typeof PERIODS;
const OPTIONS: { key: PeriodKey; label: string }[] = [
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
];

// One hue, light to dark with speed. On a dark surface "more" reads as
// brighter, so the strongest winds get the lightest step.
const SPEED_COLOURS = ["#1f6f99", "#2f9fd0", "#6cc4e8", "#bde7f6"];

const SIZE = 300;
const CENTRE = SIZE / 2;
const RADIUS = 108;
const HALF_WIDTH = 9; // degrees either side of a sector's centre, leaving a small gap

const COMPASS_LABELS: { label: string; degrees: number; major: boolean }[] = [
  { label: "N", degrees: 0, major: true },
  { label: "E", degrees: 90, major: true },
  { label: "S", degrees: 180, major: true },
  { label: "W", degrees: 270, major: true },
  { label: "NE", degrees: 45, major: false },
  { label: "SE", degrees: 135, major: false },
  { label: "SW", degrees: 225, major: false },
  { label: "NW", degrees: 315, major: false },
];

function polar(radius: number, degrees: number): [number, number] {
  const angle = (degrees * Math.PI) / 180;
  return [CENTRE + radius * Math.sin(angle), CENTRE - radius * Math.cos(angle)];
}

function wedge(inner: number, outer: number, from: number, to: number): string {
  const [ox0, oy0] = polar(outer, from);
  const [ox1, oy1] = polar(outer, to);
  const [ix1, iy1] = polar(inner, to);
  const [ix0, iy0] = polar(inner, from);
  return `M${ox0} ${oy0} A${outer} ${outer} 0 0 1 ${ox1} ${oy1} L${ix1} ${iy1} A${inner} ${inner} 0 0 0 ${ix0} ${iy0} Z`;
}

/** The outer ring: the next round number above the busiest sector. */
function ringMax(maxPercent: number): number {
  if (maxPercent <= 0) {
    return 1;
  }
  return maxPercent <= 5 ? Math.ceil(maxPercent) : Math.ceil(maxPercent / 5) * 5;
}

function Rose({ rose }: { rose: WindRoseResponse }) {
  const outerRing = ringMax(rose.max_sector_percent);
  const scale = (percent: number) => (RADIUS * percent) / outerRing;
  const busiest = rose.sectors.reduce((best, sector) => (sector.percent > best.percent ? sector : best), rose.sectors[0]);
  const summary =
    rose.readings === 0 || busiest.percent === 0
      ? "No wind recorded in this period"
      : `Most often from the ${busiest.direction}, ${busiest.percent}% of the time`;

  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`Wind rose. ${summary}.`} className="w-full max-w-[320px]">
        {[0.5, 1].map((fraction) => (
          <g key={fraction}>
            <circle cx={CENTRE} cy={CENTRE} r={RADIUS * fraction} fill="none" stroke="#1e293b" strokeWidth={1} />
            <text x={CENTRE + 3} y={CENTRE - RADIUS * fraction - 3} fontSize={10} className="fill-slate-500">
              {outerRing * fraction}%
            </text>
          </g>
        ))}
        {rose.sectors.map((sector) => {
          let inner = 0;
          return sector.counts.map((count, binIndex) => {
            const percent = rose.readings ? (100 * count) / rose.readings : 0;
            const outer = inner + scale(percent);
            const path = percent > 0 ? wedge(inner, outer, sector.degrees - HALF_WIDTH, sector.degrees + HALF_WIDTH) : null;
            inner = outer;
            return path ? (
              <path key={`${sector.direction}-${binIndex}`} d={path} fill={SPEED_COLOURS[binIndex]} stroke="#0f172a" strokeWidth={1}>
                <title>{`From the ${sector.direction}, ${rose.bins[binIndex].label}: ${percent.toFixed(1)}%`}</title>
              </path>
            ) : null;
          });
        })}
        {COMPASS_LABELS.map(({ label, degrees, major }) => {
          const [x, y] = polar(RADIUS + 16, degrees);
          return (
            <text
              key={label}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={major ? 13 : 10}
              className={major ? "fill-slate-300 font-semibold" : "fill-slate-500"}
            >
              {label}
            </text>
          );
        })}
      </svg>

      <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-slate-400">
        {rose.bins.map((bin, index) => (
          <li key={bin.label} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SPEED_COLOURS[index] }} />
            {bin.label}
          </li>
        ))}
      </ul>
      <p className="text-center text-xs text-slate-400">
        {summary}
        {rose.readings > 0 ? ` · calm ${rose.calm_percent}% of the time (not drawn)` : ""}
      </p>
    </div>
  );
}

export function WindRose() {
  const [period, setPeriod] = useState<PeriodKey>("30d");
  const { data, error } = usePolling(() => fetchWindRose(PERIODS[period]), 300_000, [period]);

  return (
    <Card
      title="Wind rose"
      note="Where the wind came from, and how strong"
      actions={<Segmented label="Wind rose period" options={OPTIONS} value={period} onChange={setPeriod} />}
    >
      {error ? (
        <p className="py-10 text-center text-sm text-red-400">{error}</p>
      ) : !data ? (
        <div className="h-[300px]" aria-busy="true" />
      ) : (
        <Rose rose={data} />
      )}
    </Card>
  );
}
