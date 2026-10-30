import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export interface TileTrend {
  direction: "up" | "down" | "steady";
  label: string;
}

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  unit?: string;
  accent?: string;
  subtext?: ReactNode;
  trend?: TileTrend | null;
  className?: string;
}

const TREND_ICONS = { up: ArrowUp, down: ArrowDown, steady: ArrowRight };

export function MetricCard({ icon: Icon, label, value, unit, accent = "text-accent-500", subtext, trend, className = "" }: MetricCardProps) {
  const TrendIcon = trend ? TREND_ICONS[trend.direction] : null;
  return (
    <div className={`flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 shadow-sm sm:gap-4 sm:p-5 ${className}`}>
      <div className={`shrink-0 rounded-lg bg-slate-800/80 p-2 sm:p-3 ${accent}`}>
        <Icon size={20} strokeWidth={2} className="sm:h-6 sm:w-6" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-xs text-slate-400 sm:text-sm">{label}</p>
        <p className="flex items-center gap-1.5 truncate text-lg font-semibold text-slate-50 sm:text-2xl">
          <span className="truncate">
            {value}
            {unit ? <span className="ml-1 text-sm font-normal text-slate-400 sm:text-base">{unit}</span> : null}
          </span>
          {trend && TrendIcon ? (
            <span title={trend.label} aria-label={trend.label} className="shrink-0 text-slate-400">
              <TrendIcon size={16} strokeWidth={2.5} />
            </span>
          ) : null}
        </p>
        {subtext ? <p className="truncate text-xs text-slate-400">{subtext}</p> : null}
      </div>
    </div>
  );
}
