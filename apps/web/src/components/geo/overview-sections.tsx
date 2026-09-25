"use client";

/**
 * Sections of the redesigned GEO Overview dashboard, ordered by the product
 * flow measure → understand → prioritize → fix. All view models come from
 * lib/geo/overview.ts and contain only data the audits actually produced.
 */

import * as React from "react";

import { ScoreRing } from "@/components/geo/score-ring";
import { SeverityBadge } from "@/components/geo/severity-badge";
import { MetricAction } from "@/components/metric-action";
import { relativeTime } from "@/lib/geo/mappers";
import {
  METRIC_HREF,
  METRIC_STATUS_LABEL,
  metricStatus,
  type MetricChange,
  type OverallScore,
  type PriorityOpportunity,
  type TrendSeriesView,
} from "@/lib/geo/overview";
import type { AuditSummary, GeoMetric } from "@/lib/geo/types";
import type { MetricKey } from "@/lib/geo/types";
import {
  Button,
  Card,
  CardContent,
  MetricCard,
  MetricCardSkeleton,
  Skeleton,
  cn,
  type MetricTone,
} from "@ai-search-growth-os/ui";

// --- MEASURE: hero --------------------------------------------------------

const SEVERITY_STRIP: Array<{ key: keyof AuditSummary; label: string; dot: string }> = [
  { key: "critical", label: "critical", dot: "bg-destructive" },
  { key: "high", label: "high", dot: "bg-warning" },
  { key: "medium", label: "medium", dot: "bg-caution" },
  { key: "low", label: "low", dot: "bg-info" },
  { key: "resolved", label: "resolved", dot: "bg-success" },
];

export function GeoHero({
  overall,
  summary,
  auditTimestamp,
  auditRunning,
  /** Real live status line while work runs (from lib/geo/progress). */
  progressText,
  pagesAnalyzed,
  loading,
  actions,
}: {
  overall: OverallScore;
  summary: AuditSummary;
  auditTimestamp: string | null;
  auditRunning: boolean;
  progressText?: string | null;
  pagesAnalyzed: number;
  loading: boolean;
  actions: React.ReactNode;
}) {
  const openIssues = summary.critical + summary.high + summary.medium + summary.low;
  return (
    <Card className="mb-6 py-5">
      <CardContent className="px-5">
        <div className="flex flex-col gap-5 md:flex-row md:items-center">
          {loading ? (
            <Skeleton className="size-[120px] shrink-0 rounded-full" />
          ) : (
            <ScoreRing value={overall.value} size={120} stroke={10} label="GEO Health" />
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold tracking-tight">GEO Health</h2>
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-relaxed">
              {overall.value == null
                ? "No audit has produced scores yet. Run a crawl and a GEO audit to measure how clearly this site can be crawled, understood and cited by AI search engines."
                : `Average of the ${overall.measured} measured score${overall.measured === 1 ? "" : "s"} below — an internal measure of how clearly this site can be crawled, understood and cited by AI search engines. Not an industry benchmark.`}
            </p>
            <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              {loading ? (
                <Skeleton className="h-4 w-64" />
              ) : (
                <>
                  <span>
                    {progressText ??
                      (auditRunning
                        ? "Audit running — results refresh automatically"
                        : auditTimestamp
                          ? `Last audit ${relativeTime(auditTimestamp)}`
                          : "No audit yet")}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span>{pagesAnalyzed} pages analyzed</span>
                  {openIssues > 0 && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>{openIssues} open issues</span>
                    </>
                  )}
                </>
              )}
            </div>
            {!loading && summary.total > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-3">
                {SEVERITY_STRIP.filter((s) => summary[s.key] > 0).map((s) => (
                  <span key={s.key} className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                    <span className={cn("size-1.5 rounded-full", s.dot)} aria-hidden="true" />
                    <span className="text-foreground font-medium tabular-nums">{summary[s.key]}</span> {s.label}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2 md:flex-col md:items-end">{actions}</div>
        </div>
      </CardContent>
    </Card>
  );
}

// --- UNDERSTAND: supporting scores ----------------------------------------

const STATUS_TONE: Record<ReturnType<typeof metricStatus>, MetricTone> = {
  healthy: "success",
  attention: "caution",
  risk: "warning",
  unmeasured: "neutral",
};

export function ScoreTile({ metric, change }: { metric: GeoMetric; change?: MetricChange }) {
  const status = metricStatus(metric.value);
  return (
    <MetricCard
      label={metric.label}
      value={metric.value == null ? "–" : Math.round(metric.value)}
      unit={metric.value == null ? undefined : "/100"}
      status={{ tone: STATUS_TONE[status], label: METRIC_STATUS_LABEL[status] }}
      delta={
        change
          ? {
              text: `${change.delta > 0 ? "+" : ""}${change.delta} points`,
              direction: change.delta > 0 ? "up" : change.delta < 0 ? "down" : "flat",
              good: change.delta === 0 ? null : change.delta > 0,
              caption: `vs audit ${relativeTime(change.previousAt)}`,
            }
          : null
      }
      progress={metric.value}
      progressTone={STATUS_TONE[status]}
      meaning={metric.description}
      context={metric.basis}
      action={<MetricAction href={METRIC_HREF[metric.key as MetricKey]} />}
      className="h-full"
    />
  );
}

export function ScoreTileSkeleton() {
  return <MetricCardSkeleton />;
}

// --- PRIORITIZE: opportunities --------------------------------------------

export function PriorityOpportunities({
  opportunities,
  loading,
  onReview,
}: {
  opportunities: PriorityOpportunity[];
  loading: boolean;
  onReview: (o: PriorityOpportunity) => void;
}) {
  if (loading) {
    return (
      <div className="grid gap-3 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-36 rounded-xl" />
        ))}
      </div>
    );
  }
  if (opportunities.length === 0) {
    return (
      <Card className="py-5">
        <CardContent className="px-5">
          <p className="text-sm font-medium">Nothing urgent right now</p>
          <p className="text-muted-foreground mt-1 text-sm">
            No open issues from the last audit. Run a new crawl and audit after site changes to keep this current.
          </p>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {opportunities.map((o) => (
        <Card key={o.code} className="py-4">
          <CardContent className="flex h-full flex-col gap-2 px-4">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={o.severity} />
              <span className="text-muted-foreground text-xs">
                {o.affectedCount === 0
                  ? "Site-wide"
                  : `${o.affectedCount} ${o.affectedCount === 1 ? "page" : "pages"} affected`}{" "}
                · {o.category}
              </span>
            </div>
            <p className="font-medium leading-snug">{o.title}</p>
            <p className="text-muted-foreground line-clamp-2 text-sm" title={o.why}>
              {o.why}
            </p>
            <div className="mt-auto flex items-center justify-between gap-3 pt-1">
              <p className="text-muted-foreground line-clamp-1 text-xs" title={o.action}>
                {o.action}
              </p>
              <Button variant="outline" size="sm" className="shrink-0" onClick={() => onReview(o)}>
                Review pages
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// --- MEASURE AGAIN: trends (real history only) ----------------------------

const TREND_COLORS: Record<TrendSeriesView["key"], string> = {
  technical_seo_health: "var(--chart-brand)",
  ai_readiness: "var(--chart-competitor-2)",
};

const W = 720;
const H = 180;
const PAD = { top: 10, right: 12, bottom: 24, left: 30 };

export function GeoTrendChart({ series }: { series: TrendSeriesView[] }) {
  const times = series.flatMap((s) => s.points.map((p) => new Date(p.at).getTime()));
  const min = Math.min(...times);
  const max = Math.max(...times);
  const x = (t: number) => PAD.left + (max === min ? 0 : ((t - min) * (W - PAD.left - PAD.right)) / (max - min));
  const y = (v: number) => PAD.top + ((100 - v) * (H - PAD.top - PAD.bottom)) / 100;
  const fmt = (t: number) =>
    new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return (
    <Card className="py-4">
      <CardContent className="px-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">Score history</p>
          <div className="flex flex-wrap gap-3">
            {series.map((s) => (
              <span key={s.key} className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                <span className="size-2 rounded-full" style={{ background: TREND_COLORS[s.key] }} aria-hidden="true" />
                {s.label}
              </span>
            ))}
          </div>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Audit score history">
          {[0, 50, 100].map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">
                {v}
              </text>
            </g>
          ))}
          {series.map((s) => (
            <g key={s.key}>
              <path
                d={s.points.map((p, i) => `${i === 0 ? "M" : "L"}${x(new Date(p.at).getTime())},${y(p.value)}`).join(" ")}
                fill="none"
                stroke={TREND_COLORS[s.key]}
                strokeWidth="2"
              />
              {s.points.map((p) => (
                <circle key={p.at} cx={x(new Date(p.at).getTime())} cy={y(p.value)} r="3" fill={TREND_COLORS[s.key]}>
                  <title>{`${s.label}: ${p.value} (${fmt(new Date(p.at).getTime())})`}</title>
                </circle>
              ))}
            </g>
          ))}
          <text x={PAD.left} y={H - 6} fontSize="10" fill="var(--muted-foreground)">
            {fmt(min)}
          </text>
          <text x={W - PAD.right} y={H - 6} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">
            {fmt(max)}
          </text>
        </svg>
        <p className="text-muted-foreground mt-1 text-xs">
          One point per completed audit. Run audits regularly to build history.
        </p>
      </CardContent>
    </Card>
  );
}
