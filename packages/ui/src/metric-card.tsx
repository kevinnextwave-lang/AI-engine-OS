import * as React from "react";
import { ArrowDownRightIcon, ArrowUpRightIcon, MinusIcon } from "lucide-react";

import { Progress } from "./progress";
import { Skeleton } from "./skeleton";
import { cn } from "./utils";

/**
 * THE metric/KPI card. One anatomy for every dashboard number:
 *
 *   LABEL                        ● Status
 *   90 /100
 *   ↑ 8 points · vs previous audit        (real history only)
 *   [progress bar or sparkline]           (optional, informative only)
 *   What the metric means right now.
 *   context line (n =, provenance)
 *   ───────────────────────────
 *   action slot ("View analysis →")
 *
 * Rules:
 * - `delta` and `spark` must come from real stored history. Callers never
 *   invent trends; without history they simply omit these props.
 * - `status` is a quiet dot + word, colored by semantic tone — not a chip.
 * - Everything after the value is optional; the card stays scannable.
 */

export type MetricTone = "success" | "caution" | "warning" | "destructive" | "info" | "neutral";

const TONE_TEXT: Record<MetricTone, string> = {
  success: "text-success",
  caution: "text-caution",
  warning: "text-warning",
  destructive: "text-destructive",
  info: "text-info",
  neutral: "text-muted-foreground",
};

const TONE_DOT: Record<MetricTone, string> = {
  success: "bg-success",
  caution: "bg-caution",
  warning: "bg-warning",
  destructive: "bg-destructive",
  info: "bg-info",
  neutral: "bg-muted-foreground/50",
};

const TONE_BAR: Record<MetricTone, string> = {
  success: "bg-success",
  caution: "bg-caution",
  warning: "bg-warning",
  destructive: "bg-destructive",
  info: "bg-info",
  neutral: "bg-muted-foreground/40",
};

export interface MetricDelta {
  /** Preformatted change, e.g. "+8 points", "−0.4", "+3pp". */
  text: string;
  direction: "up" | "down" | "flat";
  /** Whether the change is favorable; null renders it neutral. */
  good: boolean | null;
  /** What it is compared against, e.g. "vs previous audit". */
  caption?: string;
}

/** Minimal inline sparkline; renders only with two or more real points. */
function Sparkline({ points, max = 100 }: { points: number[]; max?: number }) {
  if (points.length < 2) return null;
  const w = 120;
  const h = 26;
  const pad = 2;
  const lo = Math.min(...points, 0);
  const hi = Math.max(...points, max);
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (points.length - 1);
  const y = (v: number) => pad + ((hi - v) * (h - 2 * pad)) / Math.max(1, hi - lo);
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1]!;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[26px] w-full" preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke="var(--primary)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      <circle cx={x(points.length - 1)} cy={y(last)} r="2.5" fill="var(--primary)" />
    </svg>
  );
}

function MetricCard({
  label,
  value,
  unit,
  status,
  delta,
  progress,
  progressTone = "neutral",
  spark,
  sparkMax,
  meaning,
  context,
  action,
  size = "default",
  className,
}: {
  /** 1. Metric name. */
  label: React.ReactNode;
  /** 2. Current value, preformatted ("90", "64%", "1.8"). */
  value: React.ReactNode;
  /** Unit rendered small after the value ("/100", "%"). */
  unit?: React.ReactNode;
  /** 4. Status word with a tone dot ("Strong", "Needs attention"). */
  status?: { tone: MetricTone; label: React.ReactNode } | null;
  /** Real change vs a previous measurement; omit when no history exists. */
  delta?: MetricDelta | null;
  /** 0–100 bar under the value; use for scores and coverage shares. */
  progress?: number | null;
  progressTone?: MetricTone;
  /** Real historical values, oldest first; needs ≥2 points to render. */
  spark?: number[] | null;
  sparkMax?: number;
  /** 3. One line: what the metric means / says right now. */
  meaning?: React.ReactNode;
  /** 5. Context: sample size, provenance, coverage ("n = 84 responses"). */
  context?: React.ReactNode;
  /** 6. Action slot, e.g. a "View analysis →" link. */
  action?: React.ReactNode;
  size?: "default" | "hero";
  className?: string;
}) {
  const showDelta = delta != null;
  const DeltaIcon =
    delta?.direction === "up" ? ArrowUpRightIcon : delta?.direction === "down" ? ArrowDownRightIcon : MinusIcon;
  return (
    <div
      data-slot="metric-card"
      // fade-in marks the moment measured content replaces the skeleton
      // (or a window/filter change swaps the numbers).
      className={cn("bg-card shadow-card animate-in fade-in flex flex-col gap-2 rounded-xl border p-4 duration-300", className)}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground truncate text-[11px] font-medium tracking-wider uppercase">{label}</p>
        {status && (
          <span className={cn("flex shrink-0 items-center gap-1.5 text-xs font-medium", TONE_TEXT[status.tone])}>
            <span className={cn("size-1.5 rounded-full", TONE_DOT[status.tone])} aria-hidden="true" />
            {status.label}
          </span>
        )}
      </div>
      <p
        data-slot="metric-card-value"
        className={cn("font-semibold tracking-tight", size === "hero" ? "text-4xl" : "text-3xl")}
      >
        {value}
        {unit != null && <span className="text-muted-foreground ml-1 text-base font-normal">{unit}</span>}
      </p>
      {showDelta && (
        <p
          className={cn(
            "flex items-center gap-1 text-xs tabular-nums",
            delta.good == null || delta.direction === "flat"
              ? "text-muted-foreground"
              : delta.good
                ? "text-success"
                : "text-destructive",
          )}
        >
          <DeltaIcon className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="font-medium">{delta.text}</span>
          {delta.caption && <span className="text-muted-foreground font-normal">· {delta.caption}</span>}
        </p>
      )}
      {spark != null && spark.length >= 2 ? (
        <Sparkline points={spark} max={sparkMax} />
      ) : progress != null ? (
        <Progress value={progress} indicatorClassName={TONE_BAR[progressTone]} aria-hidden="true" />
      ) : null}
      {meaning && <p className="line-clamp-2 text-sm leading-snug">{meaning}</p>}
      {context && <p className="text-muted-foreground text-xs">{context}</p>}
      {action && <div className="mt-auto flex items-center justify-end border-t pt-2">{action}</div>}
    </div>
  );
}

function MetricCardSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("bg-card shadow-card flex flex-col gap-2.5 rounded-xl border p-4", className)}>
      <Skeleton className="h-3.5 w-28" />
      <Skeleton className="h-9 w-20" />
      <Skeleton className="h-3 w-32" />
      <Skeleton className="h-3.5 w-full" />
    </div>
  );
}

export { MetricCard, MetricCardSkeleton };
