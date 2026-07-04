interface WindCompassProps {
  directionDeg: number | null;
  speedKmH: number | null;
  gustKmH: number | null;
}

const ORDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

function ordinalFor(deg: number): string {
  const index = Math.round(deg / 45) % 8;
  return ORDINALS[index];
}

export function WindCompass({ directionDeg, speedKmH, gustKmH }: WindCompassProps) {
  const hasDirection = directionDeg !== null;
  const rotation = directionDeg ?? 0;

  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <p className="self-start text-sm text-slate-400">Wind</p>
      <svg viewBox="0 0 200 200" className="h-40 w-40">
        <circle cx="100" cy="100" r="92" fill="none" stroke="#1e293b" strokeWidth="2" />
        <circle cx="100" cy="100" r="70" fill="none" stroke="#1e293b" strokeWidth="1" />
        {ORDINALS.map((label, index) => {
          const angle = (index * 45 * Math.PI) / 180;
          const x = 100 + 78 * Math.sin(angle);
          const y = 100 - 78 * Math.cos(angle);
          return (
            <text
              key={label}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-slate-500 text-xs font-medium"
            >
              {label}
            </text>
          );
        })}
        <g
          style={{
            transform: `rotate(${rotation}deg)`,
            transformOrigin: "100px 100px",
            transition: "transform 0.6s ease-out",
          }}
        >
          <polygon points="100,28 110,100 100,84 90,100" fill={hasDirection ? "#38bdf8" : "#334155"} />
        </g>
        <circle cx="100" cy="100" r="6" fill="#0ea5e9" />
      </svg>
      <div className="text-center">
        <p className="text-2xl font-semibold text-slate-50">
          {speedKmH !== null ? speedKmH.toFixed(1) : "--"}
          <span className="ml-1 text-base font-normal text-slate-400">km/h</span>
        </p>
        <p className="text-sm text-slate-400">
          {hasDirection ? `${ordinalFor(rotation)} · ${rotation.toFixed(0)}°` : "no direction data"}
          {gustKmH !== null ? ` · gusts ${gustKmH.toFixed(1)} km/h` : ""}
        </p>
      </div>
    </div>
  );
}
