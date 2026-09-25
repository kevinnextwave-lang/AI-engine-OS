/**
 * Pure view models for the GEO Overview dashboard. Everything here is derived
 * from data the audits already produced — nothing is estimated, projected or
 * invented. Where history does not exist, the corresponding view model is
 * simply absent and the UI renders nothing for it.
 */

import type { AiReadinessAudit, ReadinessCategory, SeoAudit, Severity } from "@ai-search-growth-os/types";

import { SEVERITY_ORDER } from "./labels";
import type { GeoIssue, GeoMetric, MetricKey } from "./types";

/** Where each supporting metric's detail view lives. */
export const METRIC_HREF: Record<MetricKey, string> = {
  technical_seo_health: "/app/geo/technical-seo",
  ai_readiness: "/app/geo/ai-readiness",
  entity_clarity: "/app/geo/ai-readiness",
  content_quality: "/app/geo/content",
  structured_data_coverage: "/app/geo/structured-data",
};

export type MetricStatus = "healthy" | "attention" | "risk" | "unmeasured";

/** Same 80/60 thresholds as every score tone in the app. */
export function metricStatus(value: number | null): MetricStatus {
  if (value == null) return "unmeasured";
  if (value >= 80) return "healthy";
  if (value >= 60) return "attention";
  return "risk";
}

export const METRIC_STATUS_LABEL: Record<MetricStatus, string> = {
  healthy: "Healthy",
  attention: "Needs attention",
  risk: "At risk",
  unmeasured: "Not measured yet",
};

// --- Overall score --------------------------------------------------------

export interface OverallScore {
  /** Unweighted mean of the measured sub-scores, or null when none exist. */
  value: number | null;
  measured: number;
  total: number;
}

export function overallScore(metrics: GeoMetric[]): OverallScore {
  const values = metrics.map((m) => m.value).filter((v): v is number => v != null);
  return {
    value: values.length > 0 ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : null,
    measured: values.length,
    total: metrics.length,
  };
}

// --- Real score history ---------------------------------------------------

export interface MetricChange {
  /** Current minus previous audit's score (real audits only). */
  delta: number;
  previousAt: string;
}

function completedDesc<T extends { status: string; completed_at: string | null }>(audits: T[]): T[] {
  return audits
    .filter((a) => a.status === "completed" && a.completed_at != null)
    .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""));
}

function readinessCategoryValue(audit: AiReadinessAudit, key: ReadinessCategory): number | null {
  const bd = audit.score_breakdown?.categories?.[key];
  if (!bd || !bd.applicable || bd.value == null) return null;
  return Math.round(bd.value * 100);
}

/**
 * Per-metric change versus the PREVIOUS completed audit, computed only from
 * stored audit history. A metric without two real data points has no entry.
 * Structured-data coverage has no audit history endpoint, so it never has one.
 */
export function metricChanges(
  seoAudits: SeoAudit[],
  readinessAudits: AiReadinessAudit[],
): Partial<Record<MetricKey, MetricChange>> {
  const out: Partial<Record<MetricKey, MetricChange>> = {};

  const [seoCur, seoPrev] = completedDesc(seoAudits).filter((a) => a.health_score != null);
  if (seoCur && seoPrev) {
    out.technical_seo_health = {
      delta: Math.round(seoCur.health_score! - seoPrev.health_score!),
      previousAt: seoPrev.completed_at!,
    };
  }

  const readiness = completedDesc(readinessAudits);
  const [rCur, rPrev] = readiness.filter((a) => a.readiness_score != null);
  if (rCur && rPrev) {
    out.ai_readiness = {
      delta: Math.round(rCur.readiness_score! - rPrev.readiness_score!),
      previousAt: rPrev.completed_at!,
    };
  }
  for (const [metric, category] of [
    ["entity_clarity", "entity_clarity"],
    ["content_quality", "content_structure"],
  ] as Array<[MetricKey, ReadinessCategory]>) {
    const [cur, prev] = readiness
      .map((a) => ({ at: a.completed_at!, value: readinessCategoryValue(a, category) }))
      .filter((p): p is { at: string; value: number } => p.value != null);
    if (cur && prev) {
      out[metric] = { delta: cur.value - prev.value, previousAt: prev.at };
    }
  }
  return out;
}

// --- Priority opportunities -----------------------------------------------

export interface PriorityOpportunity {
  /** Issue code, unique per opportunity. */
  code: string;
  title: string;
  severity: Severity;
  category: string;
  /** Union of pages known to be affected across this code's observations. */
  affectedCount: number;
  why: string;
  action: string;
  /** The underlying observations, most severe first; first one backs the CTA. */
  issues: GeoIssue[];
}

/**
 * The open issues that matter most, grouped by issue code so one systemic
 * problem ("structured data missing" on 95 pages) is one row, ranked by
 * severity and then by reach. Informational observations are excluded.
 */
export function priorityOpportunities(issues: GeoIssue[], max = 4): PriorityOpportunity[] {
  const groups = new Map<string, GeoIssue[]>();
  for (const issue of issues) {
    if (issue.status !== "open" || issue.severity === "info") continue;
    const list = groups.get(issue.code) ?? [];
    list.push(issue);
    groups.set(issue.code, list);
  }
  const opportunities: PriorityOpportunity[] = [];
  for (const [code, group] of groups) {
    const sorted = [...group].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
    const lead = sorted[0];
    if (!lead) continue;
    const pages = new Set<string>();
    for (const i of sorted) for (const p of i.affectedPages) pages.add(p);
    // Evidence counts can exceed the (capped) page lists; never understate.
    const affectedCount = Math.max(pages.size, ...sorted.map((i) => i.affectedCount));
    opportunities.push({
      code,
      title: lead.title,
      severity: lead.severity,
      category: lead.category,
      affectedCount,
      why: lead.description,
      action: lead.recommendation,
      issues: sorted,
    });
  }
  return opportunities
    .sort(
      (a, b) =>
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        b.affectedCount - a.affectedCount ||
        a.title.localeCompare(b.title),
    )
    .slice(0, max);
}

// --- AI discoverability recommendations -----------------------------------

export interface AiRecommendation {
  /** The audit's own recommendation text, verbatim. */
  action: string;
  fromTitle: string;
  severity: Severity;
  issue: GeoIssue;
}

/**
 * Recommendations that specifically improve AI discoverability, taken verbatim
 * from open audit observations: AI-readiness observations first, then
 * structured-data findings from the technical audit. Nothing is generated.
 */
export function aiRecommendations(issues: GeoIssue[], max = 3): AiRecommendation[] {
  const relevant = issues.filter(
    (i) =>
      i.status === "open" &&
      i.severity !== "info" &&
      i.recommendation.trim().length > 0 &&
      (i.origin === "ai_readiness" || i.categoryKey === "structured_data"),
  );
  const sorted = [...relevant].sort(
    (a, b) =>
      Number(b.origin === "ai_readiness") - Number(a.origin === "ai_readiness") ||
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      b.affectedCount - a.affectedCount,
  );
  const seen = new Set<string>();
  const out: AiRecommendation[] = [];
  for (const issue of sorted) {
    if (seen.has(issue.recommendation)) continue;
    seen.add(issue.recommendation);
    out.push({ action: issue.recommendation, fromTitle: issue.title, severity: issue.severity, issue });
    if (out.length >= max) break;
  }
  return out;
}

// --- Trends (real audit history only) -------------------------------------

export interface TrendPoint {
  at: string;
  value: number;
}

export interface TrendSeriesView {
  key: "technical_seo_health" | "ai_readiness";
  label: string;
  points: TrendPoint[];
}

/**
 * Score history from stored audits, oldest first. A series appears only with
 * at least two real data points; with none qualifying the result is null and
 * the dashboard renders no trend section at all.
 */
export function geoTrends(seoAudits: SeoAudit[], readinessAudits: AiReadinessAudit[]): TrendSeriesView[] | null {
  const series: TrendSeriesView[] = [];
  const seo = completedDesc(seoAudits)
    .filter((a) => a.health_score != null)
    .map((a) => ({ at: a.completed_at!, value: Math.round(a.health_score!) }))
    .reverse();
  if (seo.length >= 2) series.push({ key: "technical_seo_health", label: "Technical SEO Health", points: seo });
  const readiness = completedDesc(readinessAudits)
    .filter((a) => a.readiness_score != null)
    .map((a) => ({ at: a.completed_at!, value: Math.round(a.readiness_score!) }))
    .reverse();
  if (readiness.length >= 2) series.push({ key: "ai_readiness", label: "AI Readiness", points: readiness });
  return series.length > 0 ? series : null;
}

// --- URL display ----------------------------------------------------------

/** Path-only display form of a URL, to keep tables scannable. */
export function displayPath(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname === "/" && !u.search ? u.hostname : `${u.pathname}${u.search}`;
  } catch {
    return url;
  }
}
