/**
 * Typed API client.
 *
 * - Access token lives in memory only (never localStorage).
 * - Refresh token is an httpOnly cookie managed by the API; we just send
 *   `credentials: "include"` and call /auth/refresh when a 401 comes back.
 */

import type {
  AiReadinessAudit,
  AiReadinessAuditDetail,
  AiReadinessAuditListResponse,
  ApiErrorBody,
  CrawlJob,
  CrawlJobListResponse,
  CrawlStartRequest,
  EntityConsistencyResponse,
  EntityListResponse,
  ProjectSchemaResponse,
  ReadinessCategory,
  SeoAudit,
  SeoAuditListResponse,
  SeoAuditStartRequest,
  SeoCategory,
  SeoObservation,
  SeoObservationListResponse,
  SeoObservationUpdateRequest,
  Severity,
  ObservationStatus,
  LoginRequest,
  Member,
  Competitor,
  CompetitiveEngines,
  CompetitiveOverview,
  CompetitivePrompts,
  CompetitiveTrends,
  CompetitiveInsightListResponse,
  InsightAnalyzeResponse,
  CompetitorCandidate,
  CompetitorCandidateAcceptRequest,
  CompetitorCandidateListResponse,
  CompetitorDiscoverRequest,
  CompetitorDiscoverResponse,
  CompetitorCreateRequest,
  Domain,
  DomainCreateRequest,
  Organization,
  Project,
  ProjectCreateRequest,
  ProjectListResponse,
  ProjectUpdateRequest,
  RegisterRequest,
  TokenResponse,
  User,
  PromptListResponse,
  PromptRunBatch,
  PromptRunListResponse,
  PromptSetListResponse,
  ProviderStatusList,
  ResponseIntelligence,
  CitationGap,
  CitationGapListResponse,
  CitationGapSummary,
  CitationGapUpdateRequest,
  CitationListResponse,
  GapAnalyzeResponse,
  GraphClaimsResponse,
  GraphOverview,
  GraphSourcesResponse,
  GraphSourceView,
  RunPromptSetRequest,
  VisibilityByEngine,
  VisibilityByPrompt,
  VisibilityCompetitors,
  VisibilityOverview,
  VisibilityTrends,
  VisibilityWindow,
} from "@ai-search-growth-os/types";

export type {
  ApiErrorBody,
  Member,
  MembershipRole,
  Organization,
  TokenResponse,
  User,
} from "@ai-search-growth-os/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<TokenResponse | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | undefined;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }
  return new ApiError(
    res.status,
    body?.error?.code ?? "unknown_error",
    body?.error?.message ?? `Request failed with status ${res.status}`,
    body?.error?.details,
  );
}

async function rawRequest<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth && accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${API_URL}${API_PREFIX}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Attempt to mint a new access token from the refresh cookie. Deduplicated. */
export async function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = rawRequest<TokenResponse>("/auth/refresh", { method: "POST" }, false)
      .then((data) => {
        accessToken = data.access_token;
        return data;
      })
      .catch(() => {
        accessToken = null;
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/** Authenticated request with one transparent refresh-and-retry on 401. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, init);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshSession();
      if (refreshed) return rawRequest<T>(path, init);
    }
    throw err;
  }
}

export const api = {
  auth: {
    register: (body: RegisterRequest) =>
      rawRequest<TokenResponse>("/auth/signup", { method: "POST", body: JSON.stringify(body) }, false),
    login: (body: LoginRequest) =>
      rawRequest<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) }, false),
    logout: () => rawRequest<{ message: string }>("/auth/logout", { method: "POST" }, false),
    me: () => request<User>("/auth/me"),
  },
  organizations: {
    list: () => request<Organization[]>("/organizations"),
    create: (body: { name: string }) =>
      request<Organization>("/organizations", { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) => request<Organization>(`/organizations/${id}`),
    members: (id: string) => request<Member[]>(`/organizations/${id}/members`),
  },
  projects: {
    list: (organizationId?: string) =>
      request<ProjectListResponse>(
        organizationId ? `/projects?organization_id=${organizationId}` : "/projects",
      ),
    create: (body: ProjectCreateRequest) =>
      request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) => request<Project>(`/projects/${id}`),
    update: (id: string, body: ProjectUpdateRequest) =>
      request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) => request<{ message: string }>(`/projects/${id}`, { method: "DELETE" }),
    domains: {
      list: (projectId: string) => request<Domain[]>(`/projects/${projectId}/domains`),
      add: (projectId: string, body: DomainCreateRequest) =>
        request<Domain>(`/projects/${projectId}/domains`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
    },
    competitors: {
      list: (projectId: string) => request<Competitor[]>(`/projects/${projectId}/competitors`),
      add: (projectId: string, body: CompetitorCreateRequest) =>
        request<Competitor>(`/projects/${projectId}/competitors`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      remove: (projectId: string, competitorId: string) =>
        request<{ message: string }>(`/projects/${projectId}/competitors/${competitorId}`, {
          method: "DELETE",
        }),
    },
  },
  competitorCandidates: {
    list: (
      projectId: string,
      params: {
        status?: string;
        source?: string;
        min_confidence?: number;
        limit?: number;
        offset?: number;
      } = {},
    ) =>
      request<CompetitorCandidateListResponse>(
        `/projects/${projectId}/competitor-candidates${qs(params)}`,
      ),
    discover: (projectId: string, body: CompetitorDiscoverRequest = {}) =>
      request<CompetitorDiscoverResponse>(`/projects/${projectId}/competitor-candidates/discover`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    get: (candidateId: string) =>
      request<CompetitorCandidate>(`/competitor-candidates/${candidateId}`),
    accept: (candidateId: string, body: CompetitorCandidateAcceptRequest = {}) =>
      request<Competitor>(`/competitor-candidates/${candidateId}/accept`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    reject: (candidateId: string) =>
      request<CompetitorCandidate>(`/competitor-candidates/${candidateId}/reject`, {
        method: "POST",
      }),
  },
  competitiveVisibility: {
    overview: (projectId: string, window: VisibilityWindow = "30d") =>
      request<CompetitiveOverview>(
        `/projects/${projectId}/competitive-visibility${qs({ window })}`,
      ),
    trends: (projectId: string) =>
      request<CompetitiveTrends>(`/projects/${projectId}/competitive-visibility/trends`),
    prompts: (projectId: string, window: VisibilityWindow = "30d") =>
      request<CompetitivePrompts>(
        `/projects/${projectId}/competitive-visibility/prompts${qs({ window })}`,
      ),
    engines: (projectId: string, window: VisibilityWindow = "30d") =>
      request<CompetitiveEngines>(
        `/projects/${projectId}/competitive-visibility/engines${qs({ window })}`,
      ),
  },
  competitiveInsights: {
    list: (
      projectId: string,
      params: {
        insight_type?: string;
        impact?: string;
        confidence?: string;
        competitor_id?: string;
        limit?: number;
        offset?: number;
      } = {},
    ) =>
      request<CompetitiveInsightListResponse>(
        `/projects/${projectId}/competitive-insights${qs(params)}`,
      ),
    analyze: (projectId: string, windowDays = 90) =>
      request<InsightAnalyzeResponse>(`/projects/${projectId}/competitive-insights/analyze`, {
        method: "POST",
        body: JSON.stringify({ window_days: windowDays }),
      }),
    forCompetitor: (competitorId: string) =>
      request<CompetitiveInsightListResponse>(`/competitors/${competitorId}/insights`),
  },
  crawl: {
    start: (projectId: string, body: CrawlStartRequest = {}) =>
      request<CrawlJob>(`/projects/${projectId}/crawl`, { method: "POST", body: JSON.stringify(body) }),
    list: (projectId: string, limit = 20) =>
      request<CrawlJobListResponse>(`/projects/${projectId}/crawl-jobs?limit=${limit}`),
    get: (crawlId: string) => request<CrawlJob>(`/crawl-jobs/${crawlId}`),
  },
  seo: {
    startAudit: (projectId: string, body: SeoAuditStartRequest = {}) =>
      request<SeoAudit>(`/projects/${projectId}/seo-audits`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    listAudits: (projectId: string, limit = 20) =>
      request<SeoAuditListResponse>(`/projects/${projectId}/seo-audits?limit=${limit}`),
    getAudit: (auditId: string) => request<SeoAudit>(`/seo-audits/${auditId}`),
    observations: (
      auditId: string,
      params: { category?: SeoCategory; severity?: Severity; status?: ObservationStatus; limit?: number; offset?: number } = {},
    ) => {
      const q = new URLSearchParams();
      if (params.category) q.set("category", params.category);
      if (params.severity) q.set("severity", params.severity);
      if (params.status) q.set("status", params.status);
      q.set("limit", String(params.limit ?? 500));
      if (params.offset) q.set("offset", String(params.offset));
      return request<SeoObservationListResponse>(`/seo-audits/${auditId}/observations?${q}`);
    },
    updateObservation: (observationId: string, body: SeoObservationUpdateRequest) =>
      request<SeoObservation>(`/seo-observations/${observationId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
  },
  entities: {
    list: (projectId: string, params: { type?: string; scope?: "page" | "project"; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.type) q.set("type", params.type);
      if (params.scope) q.set("scope", params.scope);
      q.set("limit", String(params.limit ?? 200));
      return request<EntityListResponse>(`/projects/${projectId}/entities?${q}`);
    },
    schema: (projectId: string) => request<ProjectSchemaResponse>(`/projects/${projectId}/schema`),
    consistency: (projectId: string) =>
      request<EntityConsistencyResponse>(`/projects/${projectId}/entity-consistency`),
    reanalyze: (projectId: string) =>
      request<{ project_id: string; queued: boolean }>(`/projects/${projectId}/entity-analysis`, {
        method: "POST",
      }),
  },
  aiReadiness: {
    startAudit: (projectId: string) =>
      request<AiReadinessAudit>(`/projects/${projectId}/ai-readiness-audits`, { method: "POST" }),
    listAudits: (projectId: string, limit = 20) =>
      request<AiReadinessAuditListResponse>(`/projects/${projectId}/ai-readiness-audits?limit=${limit}`),
    getAudit: (auditId: string, params: { category?: ReadinessCategory; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.category) q.set("category", params.category);
      q.set("limit", String(params.limit ?? 500));
      return request<AiReadinessAuditDetail>(`/ai-readiness-audits/${auditId}?${q}`);
    },
  },
  ai: {
    providers: () => request<ProviderStatusList>("/ai/providers"),
  },
  prompts: {
    listSets: (projectId: string) =>
      request<PromptSetListResponse>(`/projects/${projectId}/prompt-sets`),
    list: (promptSetId: string, limit = 200) =>
      request<PromptListResponse>(`/prompt-sets/${promptSetId}/prompts?limit=${limit}`),
    run: (promptSetId: string, body: RunPromptSetRequest) =>
      request<PromptRunBatch>(`/prompt-sets/${promptSetId}/run`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    runs: (promptId: string, limit = 50) =>
      request<PromptRunListResponse>(`/prompts/${promptId}/runs?limit=${limit}`),
  },
  intelligence: {
    forRun: (runId: string) => request<ResponseIntelligence>(`/prompt-runs/${runId}/intelligence`),
  },
  visibility: {
    overview: (projectId: string, window: VisibilityWindow) =>
      request<VisibilityOverview>(`/projects/${projectId}/visibility?window=${window}`),
    trends: (projectId: string) => request<VisibilityTrends>(`/projects/${projectId}/visibility/trends`),
    byEngine: (projectId: string, window: VisibilityWindow) =>
      request<VisibilityByEngine>(`/projects/${projectId}/visibility/by-engine?window=${window}`),
    byPrompt: (projectId: string, window: VisibilityWindow) =>
      request<VisibilityByPrompt>(`/projects/${projectId}/visibility/by-prompt?window=${window}`),
    competitors: (projectId: string, window: VisibilityWindow) =>
      request<VisibilityCompetitors>(`/projects/${projectId}/visibility/competitors?window=${window}`),
  },
  intelligenceGraph: {
    overview: (projectId: string, params: GraphParams & { source_type?: string; top_sources?: number; top_prompts?: number; top_claims?: number } = {}) =>
      request<GraphOverview>(`/projects/${projectId}/graph/overview?${qs(params)}`),
    sources: (projectId: string, params: GraphParams & { view?: GraphSourceView; source_type?: string; limit?: number; offset?: number } = {}) =>
      request<GraphSourcesResponse>(`/projects/${projectId}/graph/sources?${qs(params)}`),
    claims: (projectId: string, params: GraphParams & { associated_with?: string; min_occurrences?: number; limit?: number; offset?: number } = {}) =>
      request<GraphClaimsResponse>(`/projects/${projectId}/graph/claims?${qs(params)}`),
  },
  citations: {
    list: (
      projectId: string,
      params: GraphParams & { source_domain_id?: string; relationship?: string; competitor?: string; prompt_id?: string; limit?: number; offset?: number } = {},
    ) => request<CitationListResponse>(`/projects/${projectId}/citations?${qs(params)}`),
  },
  citationGaps: {
    list: (
      projectId: string,
      params: { source_type?: string; gap_type?: string; status?: string; confidence?: string; competitor?: string; min_score?: number; max_score?: number; limit?: number; offset?: number } = {},
    ) => request<CitationGapListResponse>(`/projects/${projectId}/citation-gaps?${qs(params)}`),
    summary: (projectId: string) => request<CitationGapSummary>(`/projects/${projectId}/citation-gaps/summary`),
    analyze: (projectId: string, windowDays?: number) =>
      request<GapAnalyzeResponse>(`/projects/${projectId}/citation-gaps/analyze${windowDays ? `?window_days=${windowDays}` : ""}`, { method: "POST" }),
    get: (gapId: string) => request<CitationGap>(`/citation-gaps/${gapId}`),
    update: (gapId: string, body: CitationGapUpdateRequest) =>
      request<CitationGap>(`/citation-gaps/${gapId}`, { method: "PATCH", body: JSON.stringify(body) }),
  },
};

interface GraphParams {
  start?: string;
  end?: string;
  provider?: string;
}

function qs(params: object): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params as Record<string, string | number | undefined | null>)) {
    if (v !== undefined && v !== "" && v !== null) q.set(k, String(v));
  }
  return q.toString();
}
