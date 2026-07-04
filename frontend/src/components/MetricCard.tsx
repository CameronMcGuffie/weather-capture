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
    <div className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm">
      <div className={`rounded-lg bg-slate-800/80 p-3 ${accent}`}>
        <Icon size={24} strokeWidth={2} />
      </div>
      <div>
        <p className="text-sm text-slate-400">{label}</p>
        <p className="text-2xl font-semibold text-slate-50">
          {value}
          {unit ? <span className="ml-1 text-base font-normal text-slate-400">{unit}</span> : null}
        </p>
      </div>
    </div>
  );
}
