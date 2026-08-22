/**
 * View models for the GEO section. These are derived from API contract types
 * (packages/types) by the mappers in ./mappers.ts; UI components render them
 * and never compute them.
 */

import type {
  AiReadinessObservation,
  CrawlJob,
  ObservationStatus,
  ReadinessCategory,
  SeoObservation,
  Severity,
} from "@ai-search-growth-os/types";

/** Where a piece of data came from. Mock data is never mixed into API data. */
export type DataSource = "api" | "mock";

export interface Sourced<T> {
  data: T;
  source: DataSource;
}

export type IssueOrigin = "technical_seo" | "ai_readiness";

export interface GeoIssue {
  id: string;
  origin: IssueOrigin;
  severity: Severity;
  title: string;
  /** Machine code, e.g. `title_missing`. */
  code: string;
  /** Human label, e.g. "Structured Data". */
  category: string;
  categoryKey: string;
  description: string;
  recommendation: string;
  evidence: Record<string, unknown>;
  /** Page the issue is anchored to (page-level issues), if any. */
  url: string | null;
  /** All affected page URLs known from the evidence (capped by the API). */
  affectedPages: string[];
  affectedCount: number;
  status: ObservationStatus;
  statusNote: string | null;
  /** Readiness observations have no triage endpoint yet. */
  canUpdateStatus: boolean;
}

export interface AuditSummary {
  critical: number;
  high: number;
  medium: number;
  low: number;
  resolved: number;
  /** Informational observations are listed separately and never counted as issues. */
  info: number;
  total: number;
}

export type MetricKey =
  | "technical_seo_health"
  | "ai_readiness"
  | "entity_clarity"
  | "content_quality"
  | "structured_data_coverage";

export interface GeoMetric {
  key: MetricKey;
  label: string;
  /** 0–100, or null when no audit has produced it yet. */
  value: number | null;
  description: string;
  /** One-line provenance, e.g. "Technical SEO audit · 2h ago". */
  basis: string;
  source: DataSource;
}

export interface CrawlOverview {
  job: CrawlJob | null;
  status: CrawlJob["status"] | "never";
  lastCrawlAt: string | null;
  pagesCrawled: number;
  pagesFailed: number;
  durationSeconds: number | null;
  /** Most recent completed technical SEO / readiness audit timestamp. */
  auditTimestamp: string | null;
  auditRunning: boolean;
}

export interface ReadinessCategoryView {
  key: ReadinessCategory;
  label: string;
  /** 0–100 or null when not applicable. */
  value: number | null;
  applicable: boolean;
  weight: number;
  how: string | null;
  explanation: string;
  observations: AiReadinessObservation[];
}

export interface ReadinessOverview {
  score: number | null;
  status: string | null;
  completedAt: string | null;
  categories: ReadinessCategoryView[];
  note: string;
}

export interface StructuredDataOverview {
  pagesCrawled: number;
  pagesWithSchema: number;
  pagesWithoutSchema: number;
  blocksTotal: number;
  blocksInvalid: number;
  formats: Record<string, number>;
  schemaTypes: Array<{ type: string; pages: number; known: boolean }>;
  knownTypesAbsent: string[];
  invalidIssues: Array<{ code: string; count: number }>;
  analyzedAt: string | null;
  note: string;
}

export type SortKey = "severity" | "title" | "category" | "affected" | "status";
export type SortDirection = "asc" | "desc";

export interface IssueFilters {
  severity: Severity | "all";
  category: string | "all";
  status: ObservationStatus | "all";
  origin: IssueOrigin | "all";
}

export type SourceObservation =
  | { origin: "technical_seo"; observation: SeoObservation }
  | { origin: "ai_readiness"; observation: AiReadinessObservation };
