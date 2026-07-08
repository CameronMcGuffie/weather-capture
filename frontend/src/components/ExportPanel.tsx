import { Download, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { buildExportUrl } from "../api/client";

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export function ExportPanel() {
  const [start, setStart] = useState(isoDaysAgo(7));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    // No trailing Z: the picked days are the user's local days, not UTC.
    const startDate = new Date(`${start}T00:00:00`);
    const endDate = new Date(`${end}T23:59:59`);
    if (!(startDate < endDate)) {
      setError("The start date must be before the end date");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      // Fetched as a blob rather than navigating to the URL, so a failed
      // export shows an inline message instead of replacing the dashboard
      // with a JSON error page.
      const response = await fetch(buildExportUrl(startDate, endDate));
      if (!response.ok) {
        throw new Error(`export failed with status ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `weather-${start}-${end}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "export failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 sm:p-5">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="export-start">
            From
          </label>
          <input
            id="export-start"
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="export-end">
            To
          </label>
          <input
            id="export-end"
            type="date"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
          />
        </div>
        <button
          type="button"
          onClick={handleExport}
          disabled={busy}
          className="flex items-center gap-2 rounded-md bg-accent-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Download size={16} />}
          Export CSV
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </div>
  );
}
