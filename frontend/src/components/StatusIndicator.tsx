import type { IngestionStatusResponse } from "../types";

interface StatusIndicatorProps {
  status: IngestionStatusResponse | null;
  fetchError: string | null;
}

const STATUS_COPY: Record<string, { label: string; dotClass: string; pulse: boolean }> = {
  running: { label: "Live", dotClass: "bg-emerald-500", pulse: true },
  starting: { label: "Starting", dotClass: "bg-amber-500", pulse: true },
  restarting: { label: "Reconnecting", dotClass: "bg-amber-500", pulse: true },
  stopped: { label: "Offline", dotClass: "bg-red-500", pulse: false },
};

export function StatusIndicator({ status, fetchError }: StatusIndicatorProps) {
  if (fetchError || !status) {
    return (
      <div className="flex items-center gap-2 text-sm text-red-400">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
        Unreachable
      </div>
    );
  }

  const copy = status.is_stale && status.status === "running"
    ? { label: "Stale", dotClass: "bg-amber-500", pulse: false }
    : STATUS_COPY[status.status];

  return (
    <div className="group relative flex items-center gap-2 text-sm text-slate-300">
      <span className="relative flex h-2.5 w-2.5">
        {copy.pulse ? (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${copy.dotClass} opacity-75`} />
        ) : null}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${copy.dotClass}`} />
      </span>
      {copy.label}
      <div className="pointer-events-none absolute right-0 top-6 z-10 hidden w-64 rounded-lg border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400 shadow-lg group-hover:block">
        <p>PID: {status.pid ?? "n/a"}</p>
        <p>Restarts: {status.restart_count}</p>
        <p>Last reading: {status.last_reading_at ? new Date(status.last_reading_at).toLocaleString() : "never"}</p>
        {status.last_error ? <p className="mt-1 text-red-400">{status.last_error}</p> : null}
      </div>
    </div>
  );
}
