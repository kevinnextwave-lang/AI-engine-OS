/**
 * Pure functions from API contract types to GEO view models. No React, no I/O.
 */

import type {
  AiReadinessAuditDetail,
  AiReadinessObservation,
  CrawlJob,
  EntityConsistencyResponse,
  ProjectSchemaResponse,
  ReadinessCategory,
  SeoAudit,
  SeoObservation,
  Severity,
} from "@ai-search-growth-os/types";

import {
  READINESS_CATEGORY_EXPLANATION,
  READINESS_CATEGORY_LABEL,
  SEVERITY_ORDER,
  categoryLabel,
} from "./labels";
import type {
  AuditSummary,
  CrawlOverview,
  DataSource,
  GeoIssue,
  GeoMetric,
  IssueFilters,
  ReadinessCategoryView,
  ReadinessOverview,
  SortDirection,
  SortKey,
  StructuredDataOverview,
} from "./types";

const KNOWN_SCHEMA_TYPES = new Set([
  "Organization",
  "Person",
  "Product",
  "Service",
  "Article",
  "BlogPosting",
  "FAQPage",
  "BreadcrumbList",
  "LocalBusiness",
  "WebSite",
  "WebPage",
  "Review",
  "AggregateRating",
  "Offer",
  "Event",
]);

/** URLs an observation touches: its own page plus any `urls`/`pages` lists in evidence. */
export function affectedPagesFromEvidence(
  url: string | null,
  evidence: Record<string, unknown>,
): { pages: string[]; count: number } {
  const pages = new Set<string>();
  if (url) pages.add(url);
  const urls = evidence.urls;
  if (Array.isArray(urls)) for (const u of urls) if (typeof u === "string") pages.add(u);
  const rows = evidence.pages ?? evidence.chains ?? evidence.redirects;
  if (Array.isArray(rows)) {
    for (const row of rows) {
      if (row && typeof row === "object") {
        const candidate = (row as Record<string, unknown>).url ?? (row as Record<string, unknown>).from;
        if (typeof candidate === "string") pages.add(candidate);
      }
    }
  }
  const count = typeof evidence.count === "number" ? Math.max(evidence.count, pages.size) : pages.size;
  return { pages: [...pages], count };
}

export function seoObservationToIssue(o: SeoObservation): GeoIssue {
  const { pages, count } = affectedPagesFromEvidence(o.url, o.evidence);
  return {
    id: o.id,
    origin: "technical_seo",
    severity: o.severity,
    title: o.title,
    code: o.code,
    category: categoryLabel(o.category),
    categoryKey: o.category,
    description: o.description,
    recommendation: o.recommendation,
    evidence: o.evidence,
    url: o.url,
    affectedPages: pages,
    affectedCount: count,
    status: o.status,
    statusNote: o.status_note,
    canUpdateStatus: true,
  };
}

export function readinessObservationToIssue(o: AiReadinessObservation): GeoIssue {
  const { pages, count } = affectedPagesFromEvidence(o.url, o.evidence);
  return {
    id: o.id,
    origin: "ai_readiness",
    severity: o.severity,
    title: o.title,
    code: o.code,
    category: READINESS_CATEGORY_LABEL[o.category],
    categoryKey: o.category,
    description: o.description,
    recommendation: o.recommendation,
    evidence: o.evidence,
    url: o.url,
    affectedPages: pages,
    affectedCount: count,
    status: "open",
    statusNote: null,
    canUpdateStatus: false,
  };
}

/** Severity counts of actionable (non-info) issues; resolved counted separately. */
export function summarize(issues: GeoIssue[]): AuditSummary {
  const s: AuditSummary = { critical: 0, high: 0, medium: 0, low: 0, resolved: 0, info: 0, total: 0 };
  for (const i of issues) {
    s.total += 1;
    if (i.status === "resolved") {
      s.resolved += 1;
      continue;
    }
    if (i.severity === "info") s.info += 1;
    else s[i.severity] += 1;
  }
  return s;
}

export function applyFilters(issues: GeoIssue[], f: IssueFilters): GeoIssue[] {
  return issues.filter(
    (i) =>
      (f.severity === "all" || i.severity === f.severity) &&
      (f.category === "all" || i.categoryKey === f.category) &&
      (f.status === "all" || i.status === f.status) &&
      (f.origin === "all" || i.origin === f.origin),
  );
}

export function sortIssues(issues: GeoIssue[], key: SortKey, dir: SortDirection): GeoIssue[] {
  const sign = dir === "asc" ? 1 : -1;
  const statusOrder = { open: 0, ignored: 1, resolved: 2 } as const;
  return [...issues].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "severity":
        cmp = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
        break;
      case "title":
        cmp = a.title.localeCompare(b.title);
        break;
      case "category":
        cmp = a.category.localeCompare(b.category);
        break;
      case "affected":
        cmp = a.affectedCount - b.affectedCount;
        break;
      case "status":
        cmp = statusOrder[a.status] - statusOrder[b.status];
        break;
    }
    if (cmp === 0) cmp = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
    if (cmp === 0) cmp = a.title.localeCompare(b.title);
    return cmp * sign;
  });
}

export function crawlOverview(
  jobs: CrawlJob[],
  seoAudits: SeoAudit[],
  readiness: AiReadinessAuditDetail | null,
): CrawlOverview {
  const job = jobs[0] ?? null;
  const latestSeo = seoAudits[0] ?? null;
  const auditTimes = [latestSeo?.completed_at, readiness?.completed_at].filter(
    (t): t is string => typeof t === "string",
  );
  return {
    job,
    status: job?.status ?? "never",
    lastCrawlAt: job?.completed_at ?? job?.started_at ?? job?.created_at ?? null,
    pagesCrawled: job?.pages_crawled ?? 0,
    pagesFailed: job?.pages_failed ?? 0,
    durationSeconds: job?.duration_seconds ?? null,
    auditTimestamp: auditTimes.sort().at(-1) ?? null,
    auditRunning:
      (latestSeo !== null && (latestSeo.status === "queued" || latestSeo.status === "running")) ||
      (readiness !== null && (readiness.status === "queued" || readiness.status === "running")),
  };
}

export function readinessOverview(audit: AiReadinessAuditDetail | null): ReadinessOverview {
  const keys = Object.keys(READINESS_CATEGORY_LABEL) as ReadinessCategory[];
  const categories: ReadinessCategoryView[] = keys.map((key) => {
    const bd = audit?.score_breakdown?.categories?.[key];
    return {
      key,
      label: READINESS_CATEGORY_LABEL[key],
      value: bd?.value == null ? null : Math.round(bd.value * 100),
      applicable: bd?.applicable ?? false,
      weight: bd?.weight ?? 0,
      how: bd?.how ?? null,
      explanation: READINESS_CATEGORY_EXPLANATION[key],
      observations: (audit?.observations ?? []).filter((o) => o.category === key),
    };
  });
  return {
    score: audit?.readiness_score ?? null,
    status: audit?.status ?? null,
    completedAt: audit?.completed_at ?? null,
    categories,
    note:
      audit?.note ??
      "AI Readiness Score is an internal product metric computed only from detected signals. It is not an industry standard and does not measure or predict AI visibility.",
  };
}

export function structuredDataOverview(schema: ProjectSchemaResponse | null): StructuredDataOverview {
  const s = schema?.summary;
  return {
    pagesCrawled: s?.pages_crawled ?? 0,
    pagesWithSchema: s?.pages_with_structured_data ?? 0,
    pagesWithoutSchema: s?.pages_without_structured_data ?? 0,
    blocksTotal: s?.blocks_total ?? 0,
    blocksInvalid: s?.blocks_invalid ?? 0,
    formats: s?.formats ?? {},
    schemaTypes: Object.entries(s?.schema_types ?? {})
      .map(([type, pages]) => ({ type, pages, known: KNOWN_SCHEMA_TYPES.has(type) }))
      .sort((a, b) => b.pages - a.pages || a.type.localeCompare(b.type)),
    knownTypesAbsent: s?.known_types_absent ?? [],
    invalidIssues: Object.entries(s?.issues_by_code ?? {})
      .map(([code, count]) => ({ code, count }))
      .sort((a, b) => b.count - a.count),
    analyzedAt: schema?.analyzed_at ?? null,
    note:
      schema?.note ??
      "Validation covers structure only; it does not assess search-engine rich-result eligibility.",
  };
}

function relative(iso: string | null): string {
  if (!iso) return "not yet run";
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "–";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m} min ${s} s`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function relativeTime(iso: string | null): string {
  return relative(iso);
}

/** The five overview metrics. Each carries its own provenance and source. */
export function buildMetrics(input: {
  seoAudit: SeoAudit | null;
  readiness: ReadinessOverview;
  structured: StructuredDataOverview;
  source: DataSource;
}): GeoMetric[] {
  const { seoAudit, readiness, structured, source } = input;
  const cat = (key: ReadinessCategory) => readiness.categories.find((c) => c.key === key) ?? null;
  const entity = cat("entity_clarity");
  const content = cat("content_structure");
  const coverage =
    structured.pagesCrawled > 0
      ? Math.round((100 * structured.pagesWithSchema) / structured.pagesCrawled)
      : null;
  return [
    {
      key: "technical_seo_health",
      label: "Technical SEO Health",
      value: seoAudit?.health_score ?? null,
      description: "Internal 0–100 score from the technical SEO audit's observations.",
      basis: seoAudit ? `Technical SEO audit · ${relative(seoAudit.completed_at)}` : "No audit yet",
      source,
    },
    {
      key: "ai_readiness",
      label: "AI Readiness",
      value: readiness.score,
      description: "Internal 0–100 coverage of clarity, authority and evidence signals.",
      basis: readiness.completedAt ? `AI readiness audit · ${relative(readiness.completedAt)}` : "No audit yet",
      source,
    },
    {
      key: "entity_clarity",
      label: "Entity Clarity",
      value: entity?.applicable ? entity.value : null,
      description: `Share of entity signals (name, description, offering, audience, geography, contact) present.${entity?.how ? ` ${entity.how}.` : ""}`,
      basis: entity?.applicable ? `${entity.how ?? "AI readiness audit"}` : "From the AI readiness audit",
      source,
    },
    {
      key: "content_quality",
      label: "Content Quality",
      value: content?.applicable ? content.value : null,
      description: `Specificity and structure of content pages (facts per sentence, thin and unstructured pages).${content?.how ? ` Formula: ${content.how}.` : ""}`,
      basis: readiness.completedAt
        ? `AI readiness audit · ${relative(readiness.completedAt)}`
        : "From the AI readiness audit",
      source,
    },
    {
      key: "structured_data_coverage",
      label: "Structured Data Coverage",
      value: coverage,
      description: "Share of crawled pages that declare any structured data (JSON-LD, Microdata, RDFa).",
      basis:
        structured.pagesCrawled > 0
          ? `${structured.pagesWithSchema} of ${structured.pagesCrawled} pages`
          : "No entity analysis yet",
      source,
    },
  ];
}

export function consistencyConflicts(c: EntityConsistencyResponse | null): number {
  return c?.items.filter((o) => o.code === "entity_value_conflict").length ?? 0;
}

export function severityTone(severity: Severity): Severity {
  return severity;
}
