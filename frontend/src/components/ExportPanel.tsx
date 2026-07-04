import { Download } from "lucide-react";
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

  const handleExport = () => {
    const startDate = new Date(`${start}T00:00:00Z`);
    const endDate = new Date(`${end}T23:59:59Z`);
    window.location.assign(buildExportUrl(startDate, endDate));
  };

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
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
        className="flex items-center gap-2 rounded-md bg-accent-600 px-4 py-2 text-sm font-medium text-white hover:bg-accent-500"
      >
        <Download size={16} />
        Export CSV
      </button>
    </div>
  );
}
