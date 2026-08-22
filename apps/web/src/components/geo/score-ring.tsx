import { cn } from "@ai-search-growth-os/ui";

/** Inline SVG ring for a 0–100 score; no chart library needed. */
export function ScoreRing({
  value,
  size = 88,
  stroke = 8,
  label,
  className,
}: {
  value: number | null;
  size?: number;
  stroke?: number;
  label?: string;
  className?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const tone = value == null ? "stroke-muted-foreground/40" : v >= 80 ? "stroke-emerald-600" : v >= 60 ? "stroke-amber-500" : "stroke-orange-600";
  return (
    <div className={cn("relative inline-flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label ? `${label}: ${value == null ? "not available" : Math.round(v)}` : undefined}>
        <circle cx={size / 2} cy={size / 2} r={r} className="stroke-muted" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          className={cn("transition-[stroke-dashoffset] duration-500", tone)}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v / 100)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="absolute text-lg font-semibold tabular-nums">{value == null ? "–" : Math.round(v)}</span>
    </div>
  );
}
