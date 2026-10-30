import type { ReactNode } from "react";

interface CardProps {
  title: string;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

/** The titled panel the dashboard's cards share. */
export function Card({ title, note, actions, children }: CardProps) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-100 sm:text-base">{title}</h2>
          {note ? <p className="text-xs text-slate-400">{note}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
