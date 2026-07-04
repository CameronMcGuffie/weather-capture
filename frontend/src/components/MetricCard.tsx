import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  unit?: string;
  accent?: string;
}

export function MetricCard({ icon: Icon, label, value, unit, accent = "text-accent-500" }: MetricCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 shadow-sm sm:gap-4 sm:p-5">
      <div className={`shrink-0 rounded-lg bg-slate-800/80 p-2 sm:p-3 ${accent}`}>
        <Icon size={20} strokeWidth={2} className="sm:h-6 sm:w-6" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-xs text-slate-400 sm:text-sm">{label}</p>
        <p className="truncate text-lg font-semibold text-slate-50 sm:text-2xl">
          {value}
          {unit ? <span className="ml-1 text-sm font-normal text-slate-400 sm:text-base">{unit}</span> : null}
        </p>
      </div>
    </div>
  );
}
