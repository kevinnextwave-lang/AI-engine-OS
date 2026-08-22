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

export type CompetitorSource = "manual" | "discovered" | "imported" | "ai_detected";
export type CompetitorStatus = "active" | "ignored" | "archived";
export type CompetitorConfidence = "high" | "medium" | "low";
export type CompetitorDomainType = "primary" | "product" | "support" | "blog" | "community" | "other";

export interface CompetitorAlias {
  id: string;
  alias: string;
  normalized_alias: string;
  created_at: string;
}

export interface CompetitorDomain {
  id: string;
  domain: string;
  domain_type: CompetitorDomainType;
  is_primary: boolean;
  created_at: string;
}

export interface CompetitorProduct {
  id: string;
  name: string;
  description: string | null;
  url: string | null;
  created_at: string;
  updated_at: string;
}

export interface Competitor {
  id: string;
  project_id: string;
  name: string;
  domain: string;
  normalized_domain: string;
  website_url: string;
  hostname: string;
  description: string | null;
  source: CompetitorSource;
  status: CompetitorStatus;
  confidence: CompetitorConfidence;
  aliases: CompetitorAlias[];
  domains: CompetitorDomain[];
  products: CompetitorProduct[];
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
  description?: string | null;
  source?: CompetitorSource;
  status?: CompetitorStatus;
  confidence?: CompetitorConfidence;
  aliases?: string[];
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

// --- Prompts & execution (Milestones 3B/3C) ------------------------------------

export type PromptCategory =
  | "discovery"
  | "comparison"
  | "recommendation"
  | "pricing"
  | "product"
  | "alternative"
  | "problem_solution"
  | "industry";
export type FunnelStage = "awareness" | "consideration" | "decision" | "purchase" | "retention";
export type PromptRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type BatchStatus = "queued" | "running" | "completed" | "partially_completed" | "failed" | "cancelled";

export interface PromptSet {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  category: PromptCategory | null;
  status: string;
  prompt_count: number;
  active_prompt_count: number;
  last_generated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromptSetListResponse {
  items: PromptSet[];
  total: number;
}

export interface PromptRunSummary {
  id: string;
  status: PromptRunStatus;
  provider_key: string | null;
  model_key: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface PromptVisibilityResult {
  brand_mentioned: boolean;
  position: number | null;
  sentiment: string;
  competitors_mentioned: string[];
  parser_version: string;
}

export interface PromptRow {
  id: string;
  prompt_set_id: string;
  project_id: string;
  prompt: string;
  category: PromptCategory;
  intent: string;
  funnel_stage: FunnelStage;
  language: string;
  country: string | null;
  priority: number;
  status: string;
  is_active: boolean;
  source: string;
  quality_score: number | null;
  last_run: PromptRunSummary | null;
  visibility_result: PromptVisibilityResult | null;
  created_at: string;
  updated_at: string;
}

export interface PromptListResponse {
  items: PromptRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunPromptSetRequest {
  providers: string[];
  models?: Record<string, string>;
  priority?: "low" | "normal" | "high";
  prompt_ids?: string[];
}

export interface ProviderStatus {
  key: string;
  configured: boolean;
  default_model: string | null;
}

export interface ProviderStatusList {
  items: ProviderStatus[];
}

export interface PromptRunBatch {
  id: string;
  project_id: string;
  prompt_set_id: string;
  status: BatchStatus;
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  cancelled_runs: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AiResponseView {
  response_text: string;
  finish_reason: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
}

export interface PromptRun {
  id: string;
  prompt_id: string;
  batch_id: string | null;
  provider_key: string | null;
  model_key: string | null;
  status: PromptRunStatus;
  attempts: number;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  response: AiResponseView | null;
}

export interface PromptRunListResponse {
  items: PromptRun[];
  total: number;
  limit: number;
  offset: number;
}

// --- Response intelligence (Milestone 3D) --------------------------------------

export type Sentiment = "positive" | "neutral" | "negative" | "mixed" | "unknown";
export type RecommendationStrength = "strong" | "moderate" | "weak" | "none" | "unknown";

export interface MentionView {
  id: string;
  brand_name: string;
  mention_text: string;
  position: number | null;
  sentiment: Sentiment;
  recommendation_strength: RecommendationStrength;
  context: string;
  source: string;
  parser_version: string;
}

export interface CompetitorMentionView extends MentionView {
  competitor_id: string | null;
}

export interface ClaimView {
  id: string;
  subject: string;
  predicate: string;
  object: string;
  confidence: number;
  context: string;
}

export interface CitationView {
  id: string;
  url: string | null;
  domain: string | null;
  anchor_text: string | null;
  citation_position: number | null;
  citation_type: string;
}

export interface ResponseIntelligence {
  prompt_run_id: string;
  ai_response_id: string;
  parser_version: string | null;
  parsed_at: string | null;
  summary: Record<string, unknown> | null;
  mentions: MentionView[];
  competitor_mentions: CompetitorMentionView[];
  claims: ClaimView[];
  citations: CitationView[];
}

// --- AI Visibility Score (Milestone 3E) ----------------------------------------

export type VisibilityWindow = "7d" | "30d" | "90d";
export type Sufficiency = "insufficient" | "low" | "moderate" | "high";
export type TrendDirection = "up" | "down" | "flat" | "unavailable";

export interface VisibilityDataQuality {
  sample_size: number;
  sufficiency: Sufficiency;
  providers: number;
  provider_keys: string[];
  models: number;
  prompts: number;
  date_range: { start: string | null; end: string | null };
  parser_versions: string[];
  minimum_sample: number;
}

export interface VisibilityComponent {
  key: string;
  value: number | null;
  weight: number;
  sample: number;
  note: string;
}

export interface VisibilityScore {
  method: string;
  score: number | null;
  mention_rate: number | null;
  recommendation_rate: number | null;
  average_position: number | null;
  citation_rate: number | null;
  sentiment: Record<string, number>;
  components: VisibilityComponent[];
  data_quality: VisibilityDataQuality;
}

export interface VisibilityPeriod {
  start: string;
  end: string;
}

export interface VisibilityScorePeriod extends VisibilityScore {
  period: VisibilityPeriod;
}

export interface VisibilityOverview {
  method: string;
  window: VisibilityWindow;
  generated_at: string;
  current: VisibilityScorePeriod;
  previous: VisibilityScorePeriod;
  change: number | null;
  trend: TrendDirection;
  reason: string | null;
  competitors_configured: number;
}

export interface VisibilityWindowTrend {
  current_score: number | null;
  previous_score: number | null;
  current_sample_size: number;
  previous_sample_size: number;
  sufficiency: Sufficiency;
  change: number | null;
  trend: TrendDirection;
  reason: string | null;
}

export interface VisibilitySeriesPoint {
  start: string;
  end: string;
  score: number | null;
  mention_rate: number | null;
  recommendation_rate: number | null;
  citation_rate: number | null;
  sample_size: number;
  sufficiency: Sufficiency;
}

export interface VisibilityMentionSeriesPoint {
  start: string;
  end: string;
  mention_rate: number | null;
  sample_size: number;
  sufficiency: Sufficiency;
}

export interface VisibilityTrends {
  method: string;
  generated_at: string;
  windows: Record<VisibilityWindow, VisibilityWindowTrend>;
  series: VisibilitySeriesPoint[];
  /** Same buckets as `series`, per provider key. */
  series_by_provider: Record<string, VisibilitySeriesPoint[]>;
  /** Mention rate per bucket for "brand" and each configured competitor. */
  series_by_competitor: Record<string, VisibilityMentionSeriesPoint[]>;
  minimum_sample: number;
}

export interface VisibilityProviderScore extends VisibilityScore {
  provider: string;
}

export interface VisibilityModelScore extends VisibilityScore {
  provider: string;
  model: string;
}

export interface VisibilityByEngine {
  method: string;
  window: VisibilityWindow;
  period: VisibilityPeriod;
  overall: VisibilityScore;
  providers: VisibilityProviderScore[];
  models: VisibilityModelScore[];
}

export interface VisibilityPromptScore {
  prompt_id: string;
  text: string;
  category: PromptCategory;
  funnel_stage: FunnelStage;
  /** Newest eligible response for this prompt inside the window. */
  last_completed_at: string | null;
  sample_size: number;
  sufficiency: Sufficiency;
  score: number | null;
  mentions: number;
  mention_rate: number | null;
  recommendation_rate: number | null;
  average_position: number | null;
  citation_rate: number | null;
  sentiment: Record<string, number>;
  providers: number;
}

export interface VisibilityByPrompt {
  method: string;
  window: VisibilityWindow;
  period: VisibilityPeriod;
  prompts: VisibilityPromptScore[];
  categories: (VisibilityScore & { category: PromptCategory })[];
  funnel_stages: (VisibilityScore & { funnel_stage: FunnelStage })[];
}

export interface VisibilityCompetitorRow {
  name: string;
  is_brand: boolean;
  mentions: number;
  mention_rate: number | null;
  recommendation_rate: number | null;
  average_position: number | null;
  positioned_mentions: number;
  sentiment_score: number | null;
  sentiment: Record<string, number>;
  share_of_voice: number | null;
}

export interface VisibilityCompetitors {
  method: string;
  window: VisibilityWindow;
  period: VisibilityPeriod;
  competitors_configured: number;
  competitive_score: number | null;
  data_quality: VisibilityDataQuality;
  rows: VisibilityCompetitorRow[];
  note: string;
}

// --- Citation intelligence (Milestones 4A–4D) ----------------------------------

export type DomainType =
  | "company"
  | "media"
  | "review"
  | "community"
  | "directory"
  | "government"
  | "education"
  | "social"
  | "forum"
  | "blog"
  | "research"
  | "other"
  | "unknown";

export type GapType =
  | "brand_absent"
  | "competitor_advantage"
  | "source_underrepresented"
  | "source_overrepresented"
  | "shared_source"
  | "emerging_source";
export type GapStatus = "new" | "reviewing" | "accepted" | "dismissed" | "in_progress" | "completed";
export type GapConfidence = "high" | "medium" | "low" | "insufficient";
export type GapPriority = "high" | "medium" | "low";

export interface CitationGap {
  id: string;
  project_id: string;
  source_domain_id: string;
  source_page_id: string | null;
  domain: string;
  display_name: string;
  source_type: DomainType;
  gap_type: GapType;
  priority: GapPriority;
  brand_citations: number;
  competitor_citations: number;
  competitors: Record<string, number>;
  relevant_response_count: number;
  opportunity_score: number;
  confidence: GapConfidence;
  explanation: string;
  status: GapStatus;
  note: string | null;
  evidence: {
    score?: number;
    raw_score?: number;
    type_multiplier?: number;
    components?: Record<string, { value: number; weight: number }>;
    inputs?: Record<string, unknown>;
    window_days?: number;
    source_relevance?: { score: number; components?: Record<string, { value: number; weight: number }> };
    top_pages?: { url: string; citations: number }[];
    [key: string]: unknown;
  };
  analysis_version: string;
  analyzed_at: string;
  created_at: string;
  updated_at: string;
}

export interface CitationGapListResponse {
  items: CitationGap[];
  total: number;
  limit: number;
  offset: number;
  analyzed_at: string | null;
}

export interface CitationGapSummary {
  project_id: string;
  analyzed_at: string | null;
  analysis_version: string;
  total: number;
  by_gap_type: Record<string, number>;
  by_status: Record<string, number>;
  by_confidence: Record<string, number>;
  by_source_type: Record<string, number>;
  by_priority: Record<string, number>;
  actionable: number;
  top_opportunities: CitationGap[];
  competitors_ahead: Record<string, number>;
  data: {
    eligible_responses: number;
    relevant_prompts: number;
    sources_observed: number;
    window_days: number;
    sufficient: boolean;
    note: string;
  };
  method: string;
}

export interface CitationGapUpdateRequest {
  status?: GapStatus;
  note?: string | null;
}

export interface GapAnalyzeResponse {
  project_id: string;
  window_days: number;
  eligible_responses: number;
  total_prompts: number;
  sources_observed: number;
  gaps_written: number;
  gaps_removed: number;
  analyzed_at: string;
}

export interface CitationRelationshipView {
  entity_name: string;
  relationship: "brand" | "competitor" | string;
  confidence: number;
}

export interface CitationListItem {
  id: string;
  url: string | null;
  domain: string | null;
  source_domain_id: string | null;
  source_page_id: string | null;
  source_type: DomainType | null;
  anchor_text: string | null;
  citation_type: string;
  citation_position: number | null;
  cited_at: string | null;
  prompt_id: string;
  prompt: string;
  prompt_run_id: string;
  provider_key: string | null;
  model_key: string | null;
  relationships: CitationRelationshipView[];
}

export interface CitationListResponse {
  items: CitationListItem[];
  total: number;
  limit: number;
  offset: number;
}

export type GraphNodeType =
  | "project"
  | "brand"
  | "competitor"
  | "prompt"
  | "response"
  | "model"
  | "source_domain"
  | "source_page"
  | "claim";
export type GraphEdgeType =
  | "has_prompt"
  | "tracks"
  | "produces"
  | "mentions"
  | "cites"
  | "claims"
  | "associated_with"
  | "competes_with"
  | "belongs_to";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: GraphEdgeType;
  weight: number;
  properties: Record<string, unknown>;
}

export interface GraphWindow {
  start: string;
  end: string;
}

export interface GraphStatistics {
  responses: number;
  prompts: number;
  models: number;
  brand_mentions: number;
  competitor_mentions: number;
  claims: number;
  citations: number;
  source_domains: number;
  source_pages: number;
  brand_citations: number;
  competitor_citations: number;
  provider: string | null;
  competitors_configured: number;
  nodes_returned: number;
  edges_returned: number;
  truncated: boolean;
}

export interface GraphOverview {
  version: string;
  project_id: string;
  window: GraphWindow;
  nodes: GraphNode[];
  edges: GraphEdge[];
  statistics: GraphStatistics;
}

export type GraphSourceView = "top" | "competitor" | "gap" | "rising";

export interface GraphSourceNode {
  source_domain_id: string;
  domain: string;
  display_name: string;
  source_type: DomainType;
  citations: number;
  responses: number;
  prompts: number;
  brand_citations: number;
  competitor_citations: number;
  competitors: Record<string, number>;
  first_cited_at: string | null;
  last_cited_at: string | null;
  competitor_share: number | null;
  brand_ratio: number | null;
  previous_citations: number | null;
  growth: number | null;
  top_pages: { source_page_id: string; url: string; citations: number }[];
}

export interface GraphSourcesResponse {
  version: string;
  project_id: string;
  window: GraphWindow;
  view: GraphSourceView;
  items: GraphSourceNode[];
  total: number;
  limit: number;
  offset: number;
}

export interface GraphClaimNode {
  subject: string;
  predicate: string;
  object: string;
  occurrences: number;
  responses: number;
  prompts: number;
  avg_confidence: number;
  associated_with: "brand" | "competitor" | "other";
  entity_name: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  examples: string[];
}

export interface GraphClaimsResponse {
  version: string;
  project_id: string;
  window: GraphWindow;
  items: GraphClaimNode[];
  total: number;
  limit: number;
  offset: number;
}
