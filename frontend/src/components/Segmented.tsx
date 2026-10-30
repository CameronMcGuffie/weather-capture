interface SegmentedProps<T extends string> {
  label: string;
  options: { key: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

/** A row of mutually exclusive buttons, styled like the chart's range selector. */
export function Segmented<T extends string>({ label, options, value, onChange }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="flex gap-1 rounded-lg bg-slate-800/60 p-1">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={value === option.key}
          onClick={() => onChange(option.key)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
            value === option.key ? "bg-accent-600 text-white" : "text-slate-400 hover:text-slate-100"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
