import { BatteryWarning, CloudRain, Droplets, Thermometer } from "lucide-react";

import { fetchLatest, fetchStatus } from "./api/client";
import { ExportPanel } from "./components/ExportPanel";
import { MetricCard } from "./components/MetricCard";
import { StatusIndicator } from "./components/StatusIndicator";
import { WeatherChart } from "./components/WeatherChart";
import { WindCompass } from "./components/WindCompass";
import { usePolling } from "./hooks/usePolling";

function formatValue(value: number | null, digits = 1): string {
  return value === null ? "--" : value.toFixed(digits);
}

export default function App() {
  const { data: latest, error: latestError } = usePolling(fetchLatest, 10_000);
  const { data: status, error: statusError } = usePolling(fetchStatus, 10_000);

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

        <div className="grid grid-cols-2 items-start gap-3 sm:gap-4 lg:grid-cols-4">
          <MetricCard
            icon={Thermometer}
            label="Temperature"
            value={formatValue(latest?.temperature_c ?? null)}
            unit="°C"
            accent="text-orange-400"
          />
          <MetricCard
            icon={Droplets}
            label="Humidity"
            value={formatValue(latest?.humidity ?? null, 0)}
            unit="%"
            accent="text-sky-400"
          />
          <MetricCard
            icon={CloudRain}
            label="Rain"
            value={formatValue(latest?.rain_mm ?? null, 1)}
            unit="mm"
            accent="text-indigo-400"
          />
          <WindCompass
            directionDeg={latest?.wind_dir_deg ?? null}
            speedKmH={latest?.wind_avg_km_h ?? null}
            gustKmH={latest?.wind_max_km_h ?? null}
          />
        </div>

        <WeatherChart />

        <ExportPanel />
      </div>
    </div>
  );
}
