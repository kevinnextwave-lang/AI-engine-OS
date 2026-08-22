/**
 * Shared API contract types. Keep in sync with apps/api/app/schemas/*.
 * Dates are ISO-8601 UTC strings; ids are UUIDs.
 */

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export interface User {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  /** Derived server-side from first_name + last_name. */
  full_name: string | null;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export type MembershipRole = "owner" | "admin" | "member" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: MembershipRole;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string | null;
  role: MembershipRole;
  joined_at: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  organization_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type ProjectStatus = "active" | "paused" | "archived";

export interface Domain {
  id: string;
  project_id: string;
  url: string;
  hostname: string;
  is_primary: boolean;
  verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface Competitor {
  id: string;
  project_id: string;
  name: string;
  website_url: string;
  hostname: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  industry: string | null;
  country: string | null;
  status: ProjectStatus;
  primary_domain: Domain | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
}

export interface ProjectCreateRequest {
  name: string;
  website_url: string;
  /** Required only when the user belongs to more than one organization. */
  organization_id?: string;
  description?: string;
  industry?: string;
  country?: string;
}

export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  industry?: string;
  country?: string;
  status?: ProjectStatus;
}

export interface DomainCreateRequest {
  url: string;
  is_primary?: boolean;
}

export interface CompetitorCreateRequest {
  name: string;
  website_url: string;
}

export interface StatusResponse {
  status: string;
}

/* ------------------------------------------------------------------------ */
/* GEO: crawl, technical SEO, structured data / entities, AI readiness       */
/* Mirrors apps/api/app/schemas/{crawl,seo,entities,ai_readiness}.py          */
/* ------------------------------------------------------------------------ */

export type CrawlStatus =
  | "queued"
  | "running"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled";
export type CrawlType = "full" | "single_page";

export interface CrawlJob {
  id: string;
  project_id: string;
  root_url: string;
  status: CrawlStatus;
  crawl_type: CrawlType;
  max_pages: number;
  max_depth: number;
  pages_discovered: number;
  pages_crawled: number;
  pages_failed: number;
  pages_skipped: number;
  duration_seconds: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrawlJobListResponse {
  items: CrawlJob[];
  total: number;
}

export interface CrawlStartRequest {
  crawl_type?: CrawlType;
  max_pages?: number;
  max_depth?: number;
  url?: string;
}

export type AuditStatus = "queued" | "running" | "completed" | "failed";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type ObservationStatus = "open" | "ignored" | "resolved";
export type SeoCategory =
  | "indexability"
  | "metadata"
  | "headings"
  | "canonicalization"
  | "internal_links"
  | "http"
  | "structured_data"
  | "mobile_html";

export interface SeoAudit {
  id: string;
  project_id: string;
  crawl_job_id: string;
  status: AuditStatus;
  pages_analyzed: number;
  observation_count: number;
  /** Technical SEO Health Score 0–100; internal metric (docs/technical-seo-health-score.md). */
  health_score: number | null;
  score_breakdown: Record<string, unknown> | null;
  summary: {
    by_severity?: Partial<Record<Severity, number>>;
    by_category?: Record<string, number>;
    html_pages?: number;
    indexable_pages?: number;
  } | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SeoAuditListResponse {
  items: SeoAudit[];
  total: number;
}

export interface SeoAuditStartRequest {
  crawl_job_id?: string;
}

export interface SeoObservation {
  id: string;
  audit_id: string;
  project_id: string;
  page_id: string | null;
  url: string | null;
  category: SeoCategory;
  code: string;
  severity: Severity;
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  recommendation: string;
  status: ObservationStatus;
  status_note: string | null;
  status_changed_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SeoObservationListResponse {
  items: SeoObservation[];
  total: number;
  limit: number;
  offset: number;
}

export interface SeoObservationUpdateRequest {
  status: ObservationStatus;
  note?: string;
}

export type StructuredDataFormat = "json_ld" | "microdata" | "rdfa";
export type EntityScope = "page" | "project";

export interface EntityLink {
  url: string;
  platform: string;
  is_authoritative: boolean;
}

export interface Entity {
  id: string;
  project_id: string;
  page_id: string | null;
  page_url: string | null;
  scope: EntityScope;
  source_format: StructuredDataFormat | null;
  entity_type: string;
  extra_types: string[];
  name: string | null;
  description: string | null;
  url: string | null;
  same_as: string[];
  identifier: string[];
  properties: Record<string, unknown>;
  json_path: string;
  is_known_type: boolean;
  links: EntityLink[];
  created_at: string;
}

export interface EntityListResponse {
  items: Entity[];
  total: number;
  limit: number;
  offset: number;
  organization: Entity | null;
  analyzed_at: string | null;
}

export interface SchemaIssue {
  id: string;
  page_id: string;
  page_url: string | null;
  structured_data_id: string | null;
  format: StructuredDataFormat;
  block_position: number;
  code: string;
  severity: string;
  message: string;
  json_path: string;
}

export interface ProjectSchemaSummary {
  pages_crawled: number;
  pages_with_structured_data: number;
  pages_without_structured_data: number;
  blocks_total: number;
  blocks_invalid: number;
  formats: Record<string, number>;
  schema_types: Record<string, number>;
  entity_types: Record<string, number>;
  known_types_present: string[];
  known_types_absent: string[];
  issues_by_code: Record<string, number>;
}

export interface ProjectSchemaResponse {
  summary: ProjectSchemaSummary;
  issues: SchemaIssue[];
  analyzed_at: string | null;
  note: string;
}

export interface EntityObservation {
  id: string;
  code: string;
  severity: string;
  title: string;
  description: string;
  entity_type: string | null;
  entity_name: string | null;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface EntityConsistencyResponse {
  items: EntityObservation[];
  total: number;
  entities_compared: number;
  analyzed_at: string | null;
  note: string;
}

export type ReadinessCategory =
  | "entity_clarity"
  | "product_clarity"
  | "evidence"
  | "authority"
  | "content_structure"
  | "faq"
  | "comparison"
  | "factual_consistency";

export interface ReadinessCategoryBreakdown {
  applicable: boolean;
  weight: number;
  value: number | null;
  how?: string;
  inputs?: Record<string, unknown>;
}

export interface ReadinessScoreBreakdown {
  method: string;
  weights: Record<string, number>;
  applicable_weight: number;
  categories: Record<ReadinessCategory, ReadinessCategoryBreakdown>;
  note: string;
}

export interface AiReadinessAudit {
  id: string;
  project_id: string;
  status: AuditStatus;
  pages_analyzed: number;
  observation_count: number;
  /** AI Readiness Score 0–100; internal metric (docs/ai-readiness-score.md). */
  readiness_score: number | null;
  score_breakdown: ReadinessScoreBreakdown | null;
  summary: {
    by_severity?: Partial<Record<Severity, number>>;
    by_category?: Record<string, number>;
    page_kinds?: Record<string, number>;
    organization_entity?: boolean;
    entities_compared?: number;
  } | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AiReadinessObservation {
  id: string;
  page_id: string | null;
  url: string | null;
  category: ReadinessCategory;
  code: string;
  severity: Severity;
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  recommendation: string;
}

export interface AiReadinessAuditDetail extends AiReadinessAudit {
  observations: AiReadinessObservation[];
  observations_total: number;
  note: string;
}

export interface AiReadinessAuditListResponse {
  items: AiReadinessAudit[];
  total: number;
}
