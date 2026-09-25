"use client";

/**
 * Citations over time: weekly counts of observed citations in the selected
 * window, split into brand-related vs other. Strictly real data: it renders
 * only when every citation in the window is loaded (items === total), so
 * weekly buckets are exact counts, never a truncated sample's shape.
 */

import * as React from "react";

import type { CitationListItem } from "@ai-search-growth-os/types";
import { Card, CardContent, Skeleton } from "@ai-search-growth-os/ui";

const W = 720;
const H = 170;
const PAD = { top: 12, right: 12, bottom: 24, left: 34 };
const WEEK_MS = 7 * 24 * 3600 * 1000;

interface WeekBucket {
  start: number;
  brand: number;
  other: number;
}

function buckets(citations: CitationListItem[], windowDays: number): WeekBucket[] {
  const dated = citations.filter((c) => c.cited_at != null);
  if (dated.length === 0) return [];
  const now = Date.now();
  const start = now - windowDays * 24 * 3600 * 1000;
  // Weeks aligned to the window start; zero weeks are real zeros because the
  // caller guarantees the full window's citations are present.
  const n = Math.ceil((now - start) / WEEK_MS);
  const out: WeekBucket[] = Array.from({ length: n }, (_, i) => ({ start: start + i * WEEK_MS, brand: 0, other: 0 }));
  for (const c of dated) {
    const t = new Date(c.cited_at!).getTime();
    const i = Math.floor((t - start) / WEEK_MS);
    if (i < 0 || i >= n) continue;
    const isBrand = c.relationships.some((r) => r.relationship === "brand");
    if (isBrand) out[i]!.brand += 1;
    else out[i]!.other += 1;
  }
  return out;
}

export function CitationsChart({
  citations,
  total,
  windowDays,
  windowLabel,
  loading,
}: {
  citations: CitationListItem[];
  total: number;
  windowDays: number;
  windowLabel: string;
  loading: boolean;
}) {
  const weeks = React.useMemo(() => buckets(citations, windowDays), [citations, windowDays]);

  if (loading) {
    return (
      <Card className="mb-4 py-4">
        <CardContent className="flex flex-col gap-2 px-4">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-36 w-full" />
        </CardContent>
      </Card>
    );
  }
  // No citations at all: the page's empty state explains; no chart to draw.
  if (total === 0) return null;
  // Partial window loaded: weekly shapes would mislead — skip rather than guess.
  if (citations.length < total || weeks.length === 0) return null;

  const max = Math.max(1, ...weeks.map((w) => w.brand + w.other));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const bw = Math.min(28, (innerW / weeks.length) * 0.6);
  const x = (i: number) => PAD.left + (weeks.length === 1 ? innerW / 2 : (i * innerW) / (weeks.length - 1 || 1));
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const fmt = (t: number) => new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const brandTotal = weeks.reduce((a, w) => a + w.brand, 0);

  return (
    <Card className="mb-4 py-4">
      <CardContent className="px-4">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium">Citations over time</p>
          <div className="text-muted-foreground flex items-center gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5">
              <span className="bg-primary size-2 rounded-full" aria-hidden="true" /> Brand-related ({brandTotal})
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="bg-chart-competitor-2 size-2 rounded-full" aria-hidden="true" /> Other ({total - brandTotal})
            </span>
          </div>
        </div>
        <p className="text-muted-foreground mb-2 text-xs">
          Observed citations per week, {windowLabel.toLowerCase()} · {total} total
        </p>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Observed citations per week">
          {[0, Math.ceil(max / 2), max].map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">
                {v}
              </text>
            </g>
          ))}
          {weeks.map((w, i) => {
            const totalW = w.brand + w.other;
            const cx = x(i) - bw / 2;
            return (
              <g key={w.start}>
                {/* other on top of brand, stacked */}
                <rect x={cx} y={y(w.brand)} width={bw} height={innerH + PAD.top - y(w.brand)} fill="var(--primary)" rx="1.5" />
                <rect x={cx} y={y(totalW)} width={bw} height={y(w.brand) - y(totalW)} fill="var(--chart-competitor-2)" rx="1.5" />
                <rect x={cx} y={PAD.top} width={bw} height={innerH} fill="transparent">
                  <title>{`Week of ${fmt(w.start)}: ${totalW} citation${totalW === 1 ? "" : "s"} (${w.brand} brand-related, ${w.other} other)`}</title>
                </rect>
              </g>
            );
          })}
          <text x={PAD.left} y={H - 6} fontSize="10" fill="var(--muted-foreground)">
            {fmt(weeks[0]!.start)}
          </text>
          <text x={W - PAD.right} y={H - 6} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">
            {fmt(weeks[weeks.length - 1]!.start)}
          </text>
        </svg>
      </CardContent>
    </Card>
  );
}
