"use client";

import * as React from "react";

import { fmtDate } from "@/components/visibility/format";
import type { ChartMode, ChartSeries } from "@/lib/visibility/types";
import { Card, CardContent, CardHeader, CardTitle, Skeleton, cn } from "@ai-search-growth-os/ui";

/** Distinct, theme-stable series colours (brand first, then competitors/providers). */
const COLORS = ["var(--primary)", "#0ea5e9", "#f59e0b", "#8b5cf6", "#10b981", "#ef4444", "#64748b"];

const MODES: { key: ChartMode; label: string; yLabel: string }[] = [
  { key: "overall", label: "Overall", yLabel: "AI Visibility Score" },
  { key: "provider", label: "By AI engine", yLabel: "AI Visibility Score" },
  { key: "competitor", label: "vs competitors", yLabel: "Mention rate (%)" },
];

const W = 720;
const H = 240;
const PAD = { top: 12, right: 16, bottom: 28, left: 36 };

function x(i: number, n: number): number {
  return PAD.left + (n <= 1 ? 0 : (i * (W - PAD.left - PAD.right)) / (n - 1));
}
function y(v: number): number {
  return PAD.top + ((100 - v) * (H - PAD.top - PAD.bottom)) / 100;
}

/** Path segments break where a bucket has no value (insufficient data). */
function segments(points: ChartSeries["points"]): string[] {
  const out: string[] = [];
  let cur: string[] = [];
  points.forEach((p, i) => {
    if (p.value == null) {
      if (cur.length > 1) out.push(cur.join(" "));
      cur = [];
      return;
    }
    cur.push(`${cur.length === 0 ? "M" : "L"}${x(i, points.length).toFixed(1)},${y(p.value).toFixed(1)}`);
  });
  if (cur.length > 1) out.push(cur.join(" "));
  return out;
}

export function TrendChart({
  series,
  mode,
  onModeChange,
  loading,
  modes = MODES.map((m) => m.key),
}: {
  series: Record<ChartMode, ChartSeries[]>;
  mode: ChartMode;
  onModeChange: (m: ChartMode) => void;
  loading?: boolean;
  modes?: ChartMode[];
}) {
  const [hover, setHover] = React.useState<number | null>(null);
  const active = series[mode];
  const n = active[0]?.points.length ?? 0;
  const meta = MODES.find((m) => m.key === mode) ?? MODES[0]!;
  const hasAny = active.some((s) => s.points.some((p) => p.value != null));

  return (
    <Card className="gap-3 py-5">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 px-5">
        <div>
          <CardTitle className="text-base">AI visibility trend</CardTitle>
          <p className="text-muted-foreground text-xs">{meta.yLabel} per week, last 90 days. Gaps = fewer than 5 responses that week.</p>
        </div>
        <div role="group" aria-label="Chart series" className="bg-muted inline-flex rounded-md p-0.5 text-xs">
          {MODES.filter((m) => modes.includes(m.key)).map((m) => (
            <button
              key={m.key}
              type="button"
              aria-pressed={mode === m.key}
              onClick={() => onModeChange(m.key)}
              className={cn(
                "rounded-[5px] px-2.5 py-1",
                mode === m.key ? "bg-background text-foreground font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="px-5">
        {loading ? (
          <Skeleton className="h-60 w-full" />
        ) : !hasAny ? (
          <div className="text-muted-foreground flex h-60 items-center justify-center rounded-lg border border-dashed text-sm">
            Not enough data in any week yet — the trend appears once a week has 5+ parsed responses.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="h-auto w-full"
              role="img"
              aria-label={`${meta.yLabel} over the last 90 days`}
              onMouseLeave={() => setHover(null)}
            >
              {[0, 25, 50, 75, 100].map((g) => (
                <g key={g}>
                  <line x1={PAD.left} x2={W - PAD.right} y1={y(g)} y2={y(g)} className="stroke-border" strokeWidth={1} />
                  <text x={PAD.left - 6} y={y(g) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
                    {g}
                  </text>
                </g>
              ))}
              {active[0]?.points.map((p, i) =>
                i % 2 === 0 ? (
                  <text key={p.date} x={x(i, n)} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                    {fmtDate(p.date)}
                  </text>
                ) : null,
              )}
              {active.map((s, si) => (
                <g key={s.key} stroke={COLORS[si % COLORS.length]} fill={COLORS[si % COLORS.length]}>
                  {segments(s.points).map((d, k) => (
                    <path key={k} d={d} fill="none" strokeWidth={si === 0 ? 2.5 : 1.75} strokeLinejoin="round" strokeLinecap="round" />
                  ))}
                  {s.points.map((p, i) =>
                    p.value == null ? null : (
                      <circle key={p.date} cx={x(i, n)} cy={y(p.value)} r={hover === i ? 4 : 2.5} stroke="none" />
                    ),
                  )}
                </g>
              ))}
              {hover != null && (
                <line x1={x(hover, n)} x2={x(hover, n)} y1={PAD.top} y2={H - PAD.bottom} className="stroke-muted-foreground/50" strokeDasharray="3 3" />
              )}
              {Array.from({ length: n }, (_, i) => (
                <rect
                  key={i}
                  x={x(i, n) - (W - PAD.left - PAD.right) / (2 * Math.max(n - 1, 1))}
                  y={PAD.top}
                  width={(W - PAD.left - PAD.right) / Math.max(n - 1, 1)}
                  height={H - PAD.top - PAD.bottom}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              ))}
            </svg>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              {active.map((s, si) => {
                const p = hover == null ? null : s.points[hover];
                return (
                  <span key={s.key} className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-2.5 rounded-full" style={{ background: COLORS[si % COLORS.length] }} />
                    <span className="text-muted-foreground">{s.label}</span>
                    {p && (
                      <span className="tabular-nums">
                        {p.value == null ? "n/a" : mode === "competitor" ? `${p.value}%` : p.value}
                        <span className="text-muted-foreground"> (n={p.sampleSize})</span>
                      </span>
                    )}
                  </span>
                );
              })}
              {hover != null && active[0]?.points[hover] && (
                <span className="text-muted-foreground ml-auto">
                  Week of {fmtDate(active[0].points[hover].date)}
                </span>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
