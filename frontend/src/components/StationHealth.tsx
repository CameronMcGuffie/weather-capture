import { fetchStationHealth } from "../api/client";
import { formatClock, formatDuration } from "../dates";
import { usePolling } from "../hooks/usePolling";
import type { StationHealthResponse } from "../types";
import { Card } from "./Card";

const WARNING = "text-amber-400";

function barColour(readings: number, expected: number | null, partial: boolean): string {
  if (partial) {
    return "bg-slate-600";
  }
  if (!expected) {
    return readings > 0 ? "bg-emerald-500" : "bg-slate-700";
  }
  const share = readings / expected;
  if (share >= 0.9) {
    return "bg-emerald-500";
  }
  if (share >= 0.5) {
    return "bg-amber-500";
  }
  return readings === 0 ? "bg-red-500/70" : "bg-orange-500";
}

function Item({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-slate-400">{label}</p>
      <p className={`truncate text-sm font-medium ${tone ?? "text-slate-100"}`}>{value}</p>
    </div>
  );
}

function gapText(health: StationHealthResponse): string {
  if (health.longest_gap_seconds === null) {
    return "–";
  }
  const duration = formatDuration(health.longest_gap_seconds);
  return health.longest_gap_ended_at && health.longest_gap_seconds > 300
    ? `${duration}, until ${formatClock(health.longest_gap_ended_at)}`
    : duration;
}

function Report({ health }: { health: StationHealthResponse }) {
  const hours = health.hours.length;
  const completeness = health.completeness_percent;
  const gap = health.longest_gap_seconds;
  return (
    <div className="space-y-4">
      <div>
        <div className="flex h-9 items-end gap-px" role="img" aria-label={`Readings received in each of the last ${hours} hours`}>
          {health.hours.map((entry) => {
            const height = health.expected_per_hour ? Math.min(100, Math.max(8, (100 * entry.readings) / health.expected_per_hour)) : 100;
            const stamp = new Date(entry.hour).toLocaleString([], { weekday: "short", hour: "numeric" });
            return (
              <div
                key={entry.hour}
                title={`${stamp}: ${entry.readings} readings${entry.partial ? " so far" : ""}`}
                className={`flex-1 rounded-sm ${barColour(entry.readings, health.expected_per_hour, entry.partial)}`}
                style={{ height: `${entry.readings === 0 ? 8 : height}%` }}
              />
            );
          })}
        </div>
        <div className="mt-1 flex justify-between text-xs text-slate-500">
          <span>{hours} h ago</span>
          <span>now</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Item
          label="Reception"
          value={completeness === null ? "–" : `${completeness}% of expected`}
          tone={completeness !== null && completeness < 90 ? WARNING : undefined}
        />
        <Item label="Longest gap (24 h)" value={gapText(health)} tone={gap !== null && gap > 900 ? WARNING : undefined} />
        <Item
          label="Sensor battery"
          value={health.battery_ok === null ? "–" : health.battery_ok ? "OK" : "Low"}
          tone={health.battery_ok === false ? WARNING : undefined}
        />
        <Item
          label="Low-battery readings (7 d)"
          value={String(health.low_battery_readings_7d)}
          tone={health.low_battery_readings_7d > 0 ? WARNING : undefined}
        />
        <Item
          label="Rain glitches held back (7 d)"
          value={String(health.rain_glitches_held_7d)}
          tone={health.rain_glitches_held_7d > 0 ? WARNING : undefined}
        />
        <Item label="Other devices ignored" value={`${health.ignored_readings_since_start} since start`} />
      </div>

      {health.restart_count > 0 ? (
        <p className="text-xs text-slate-400">
          The radio process has restarted {health.restart_count} time{health.restart_count === 1 ? "" : "s"} since the app started.
        </p>
      ) : null}
    </div>
  );
}

/** Whether the station's readings are arriving reliably, hour by hour. */
export function StationHealth() {
  const { data, error } = usePolling(() => fetchStationHealth(48), 60_000);

  return (
    <Card title="Station health" note="Readings received per hour">
      {error ? (
        <p className="py-6 text-center text-sm text-red-400">{error}</p>
      ) : !data ? (
        <div className="h-[170px]" aria-busy="true" />
      ) : (
        <Report health={data} />
      )}
    </Card>
  );
}
