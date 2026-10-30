import { BatteryWarning, CloudRain, Droplets, Thermometer, ThermometerSnowflake, ThermometerSun } from "lucide-react";

import { fetchLatest, fetchNow, fetchStatus, fetchSummary } from "./api/client";
import { formatAgo } from "./dates";
import { ExportPanel } from "./components/ExportPanel";
import { MetricCard } from "./components/MetricCard";
import type { TileTrend } from "./components/MetricCard";
import { RainBars } from "./components/RainBars";
import { RecordsCard } from "./components/RecordsCard";
import { StationHealth } from "./components/StationHealth";
import { StatusIndicator } from "./components/StatusIndicator";
import { TodayCard } from "./components/TodayCard";
import { WeatherChart } from "./components/WeatherChart";
import { WindCompass } from "./components/WindCompass";
import { WindRose } from "./components/WindRose";
import { usePolling } from "./hooks/usePolling";
import type { NowResponse } from "./types";

function formatValue(value: number | null, digits = 1): string {
  return value === null ? "--" : value.toFixed(digits);
}

/** An arrow only when the change is big enough to mean something. */
function describeTrend(change: number | null | undefined, threshold: number, unit: string, hours: number): TileTrend | null {
  if (change === null || change === undefined) {
    return null;
  }
  const size = `${Math.abs(change).toFixed(unit === "%" ? 0 : 1)}${unit}`;
  if (change >= threshold) {
    return { direction: "up", label: `Up ${size} over the last ${hours} hours` };
  }
  if (change <= -threshold) {
    return { direction: "down", label: `Down ${size} over the last ${hours} hours` };
  }
  return { direction: "steady", label: `Steady over the last ${hours} hours` };
}

function rainStatus(now: NowResponse | null): string | undefined {
  if (!now) {
    return undefined;
  }
  if (now.rain.raining) {
    return `Raining · ${now.rain.last_15_min_mm?.toFixed(1)} mm in 15 min`;
  }
  return now.rain.last_rain_at ? `Dry · last rain ${formatAgo(now.rain.last_rain_at)}` : "Dry · no rain in 90 days";
}

export default function App() {
  const { data: latest, error: latestError } = usePolling(fetchLatest, 10_000);
  const { data: status, error: statusError } = usePolling(fetchStatus, 10_000);
  const { data: summary } = usePolling(() => fetchSummary(24), 60_000);
  const { data: now } = usePolling(fetchNow, 30_000);

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8 sm:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-50">Weather Station</h1>
            <p className="text-sm text-slate-400">
              {latest ? `Fine Offset ${latest.model ?? "sensor"} · id ${latest.sensor_id ?? "n/a"}` : "Waiting for data"}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {latest?.battery_ok === 0 && (
              <span className="flex items-center gap-1 text-sm text-amber-400">
                <BatteryWarning size={16} />
                Low battery
              </span>
            )}
            <StatusIndicator status={status} fetchError={statusError} />
          </div>
        </header>

        {latestError && (
          <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
            Unable to reach the API: {latestError}
          </div>
        )}

        <div className="grid grid-cols-2 items-start gap-3 sm:gap-4 lg:grid-cols-3 lg:items-stretch">
          <MetricCard
            icon={Thermometer}
            label="Temperature"
            value={formatValue(latest?.temperature_c ?? null)}
            unit="°C"
            accent="text-orange-400"
            subtext={now?.feels_like_c != null ? `Feels like ${now.feels_like_c.toFixed(1)}°` : undefined}
            trend={describeTrend(now?.trend.temperature_c, 0.5, "°", now?.trend.hours ?? 3)}
          />
          <MetricCard
            icon={Droplets}
            label="Humidity"
            value={formatValue(latest?.humidity ?? null, 0)}
            unit="%"
            accent="text-sky-400"
            subtext={now?.dew_point_c != null ? `Dew point ${now.dew_point_c.toFixed(1)}°` : undefined}
            trend={describeTrend(now?.trend.humidity, 3, "%", now?.trend.hours ?? 3)}
          />
          <MetricCard
            icon={CloudRain}
            label="Rain (24h)"
            value={formatValue(summary?.rain_mm ?? null, 1)}
            unit="mm"
            accent="text-indigo-400"
            subtext={rainStatus(now)}
            className="col-span-2 lg:col-span-1"
          />
          <MetricCard
            icon={ThermometerSnowflake}
            label="24h Low"
            value={formatValue(summary?.temperature_c_min ?? null)}
            unit="°C"
            accent="text-cyan-400"
          />
          <MetricCard
            icon={ThermometerSun}
            label="24h High"
            value={formatValue(summary?.temperature_c_max ?? null)}
            unit="°C"
            accent="text-amber-400"
          />
          <WindCompass
            directionDeg={latest?.wind_dir_deg ?? null}
            speedKmH={latest?.wind_avg_km_h ?? null}
            gustKmH={latest?.wind_max_km_h ?? null}
            className="col-span-2 lg:col-span-1"
          />
        </div>

        <TodayCard />

        <WeatherChart />

        <div className="grid gap-6 lg:grid-cols-2">
          <RainBars />
          <WindRose />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <RecordsCard />
          <StationHealth />
        </div>

        <ExportPanel />
      </div>
    </div>
  );
}
