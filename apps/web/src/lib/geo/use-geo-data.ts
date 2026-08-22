"use client";

/**
 * Loads everything the GEO section needs for one project and derives the view
 * models. Components consume the result; they never call the API directly.
 *
 * Data provenance is explicit: `source === "api"` means every dataset came
 * from the backend for the selected project; `source === "mock"` means the
 * bundled sample data is shown (no project selected, or the API could not be
 * reached). The two are never mixed.
 */

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import type {
  AiReadinessAuditDetail,
  CrawlJob,
  EntityConsistencyResponse,
  EntityListResponse,
  ObservationStatus,
  ProjectSchemaResponse,
  SeoAudit,
  SeoObservation,
} from "@ai-search-growth-os/types";

import {
  buildMetrics,
  crawlOverview,
  readinessObservationToIssue,
  readinessOverview,
  seoObservationToIssue,
  structuredDataOverview,
  summarize,
} from "./mappers";
import {
  MOCK_CONSISTENCY,
  MOCK_CRAWL_JOBS,
  MOCK_ENTITIES,
  MOCK_READINESS,
  MOCK_SCHEMA,
  MOCK_SEO_AUDIT,
  MOCK_SEO_OBSERVATIONS,
} from "./mock";
import type {
  AuditSummary,
  CrawlOverview,
  DataSource,
  GeoIssue,
  GeoMetric,
  ReadinessOverview,
  StructuredDataOverview,
} from "./types";

interface RawData {
  crawlJobs: CrawlJob[];
  seoAudits: SeoAudit[];
  seoObservations: SeoObservation[];
  schema: ProjectSchemaResponse | null;
  entities: EntityListResponse | null;
  consistency: EntityConsistencyResponse | null;
  readiness: AiReadinessAuditDetail | null;
}

export interface GeoData {
  source: DataSource;
  /** Why mock data is shown (only when source === "mock"). */
  mockReason: string | null;
  loading: boolean;
  error: string | null;
  raw: RawData;
  issues: GeoIssue[];
  summary: AuditSummary;
  metrics: GeoMetric[];
  crawl: CrawlOverview;
  readiness: ReadinessOverview;
  structured: StructuredDataOverview;
  latestSeoAudit: SeoAudit | null;
  actions: {
    refresh: () => void;
    runCrawl: () => Promise<void>;
    runGeoAudit: () => Promise<void>;
    updateIssueStatus: (issue: GeoIssue, status: ObservationStatus, note?: string) => Promise<void>;
  };
  /** In-flight action name, for button states. */
  busy: "crawl" | "audit" | "status" | null;
}

const MOCK_RAW: RawData = {
  crawlJobs: MOCK_CRAWL_JOBS,
  seoAudits: [MOCK_SEO_AUDIT],
  seoObservations: MOCK_SEO_OBSERVATIONS,
  schema: MOCK_SCHEMA,
  entities: MOCK_ENTITIES,
  consistency: MOCK_CONSISTENCY,
  readiness: MOCK_READINESS,
};

const EMPTY_RAW: RawData = {
  crawlJobs: [],
  seoAudits: [],
  seoObservations: [],
  schema: null,
  entities: null,
  consistency: null,
  readiness: null,
};

const POLL_MS = 5000;

function isActive(status: string | undefined): boolean {
  return status === "queued" || status === "running";
}

async function loadFromApi(projectId: string): Promise<RawData> {
  const [crawls, seoAudits, schema, entities, consistency, readinessList] = await Promise.all([
    api.crawl.list(projectId),
    api.seo.listAudits(projectId),
    api.entities.schema(projectId),
    api.entities.list(projectId),
    api.entities.consistency(projectId),
    api.aiReadiness.listAudits(projectId),
  ]);
  const latestSeo = seoAudits.items.find((a) => a.status === "completed") ?? null;
  const seoObservations = latestSeo ? (await api.seo.observations(latestSeo.id)).items : [];
  const latestReadiness = readinessList.items.find((a) => a.status === "completed") ?? readinessList.items[0];
  const readiness = latestReadiness ? await api.aiReadiness.getAudit(latestReadiness.id) : null;
  return {
    crawlJobs: crawls.items,
    seoAudits: seoAudits.items,
    seoObservations,
    schema,
    entities,
    consistency,
    readiness,
  };
}

function isNetworkFailure(err: unknown): boolean {
  return !(err instanceof ApiError);
}

interface Loaded {
  projectId: string;
  raw: RawData;
  source: DataSource;
  mockReason: string | null;
  error: string | null;
}

const NO_PROJECT: Omit<Loaded, "projectId"> = {
  raw: MOCK_RAW,
  source: "mock",
  mockReason: "No project selected — showing sample data.",
  error: null,
};

export function useGeoData(projectId: string | null): GeoData {
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [busy, setBusy] = React.useState<GeoData["busy"]>(null);
  const [version, setVersion] = React.useState(0);

  React.useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    loadFromApi(projectId)
      .then((data) => {
        if (!cancelled) setLoaded({ projectId, raw: data, source: "api", mockReason: null, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isNetworkFailure(err)) {
          setLoaded({
            projectId,
            raw: MOCK_RAW,
            source: "mock",
            mockReason: "The API could not be reached — showing sample data.",
            error: null,
          });
        } else {
          setLoaded({
            projectId,
            raw: EMPTY_RAW,
            source: "api",
            mockReason: null,
            error: err instanceof Error ? err.message : "Request failed",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, version]);

  // Resolve what to show for this render without touching state.
  const current: Omit<Loaded, "projectId"> | null = !projectId
    ? NO_PROJECT
    : loaded?.projectId === projectId
      ? loaded
      : null;
  const loading = current === null;
  const raw = current?.raw ?? EMPTY_RAW;
  const source: DataSource = current?.source ?? "api";
  const mockReason = current?.mockReason ?? null;
  const error = current?.error ?? null;

  const setRaw = React.useCallback(
    (update: (prev: RawData) => RawData) => {
      if (!projectId) return;
      setLoaded((prev) => (prev && prev.projectId === projectId ? { ...prev, raw: update(prev.raw) } : prev));
    },
    [projectId],
  );

  // Poll while a crawl or audit is in flight.
  const active =
    source === "api" &&
    (isActive(raw.crawlJobs[0]?.status) ||
      isActive(raw.seoAudits[0]?.status) ||
      isActive(raw.readiness?.status));
  React.useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setVersion((v) => v + 1), POLL_MS);
    return () => window.clearInterval(id);
  }, [active]);

  const refresh = React.useCallback(() => setVersion((v) => v + 1), []);

  const runCrawl = React.useCallback(async () => {
    if (!projectId || source !== "api") return;
    setBusy("crawl");
    try {
      await api.crawl.start(projectId);
      refresh();
    } finally {
      setBusy(null);
    }
  }, [projectId, source, refresh]);

  const runGeoAudit = React.useCallback(async () => {
    if (!projectId || source !== "api") return;
    setBusy("audit");
    try {
      await api.entities.reanalyze(projectId);
      await api.seo.startAudit(projectId);
      await api.aiReadiness.startAudit(projectId);
      refresh();
    } finally {
      setBusy(null);
    }
  }, [projectId, source, refresh]);

  const updateIssueStatus = React.useCallback(
    async (issue: GeoIssue, status: ObservationStatus, note?: string) => {
      if (!issue.canUpdateStatus) return;
      if (source !== "api") {
        // Sample data is read-only; there is nothing to persist.
        return;
      }
      setBusy("status");
      try {
        const updated = await api.seo.updateObservation(issue.id, { status, note });
        setRaw((prev) => ({
          ...prev,
          seoObservations: prev.seoObservations.map((o) => (o.id === updated.id ? updated : o)),
        }));
      } finally {
        setBusy(null);
      }
    },
    [source, setRaw],
  );

  return React.useMemo<GeoData>(() => {
    const issues = [
      ...raw.seoObservations.map(seoObservationToIssue),
      ...(raw.readiness?.observations ?? []).map(readinessObservationToIssue),
    ];
    const latestSeoAudit = raw.seoAudits.find((a) => a.status === "completed") ?? raw.seoAudits[0] ?? null;
    const readiness = readinessOverview(raw.readiness);
    const structured = structuredDataOverview(raw.schema);
    return {
      source,
      mockReason,
      loading,
      error,
      raw,
      issues,
      summary: summarize(issues),
      metrics: buildMetrics({ seoAudit: latestSeoAudit, readiness, structured, source }),
      crawl: crawlOverview(raw.crawlJobs, raw.seoAudits, raw.readiness),
      readiness,
      structured,
      latestSeoAudit,
      actions: { refresh, runCrawl, runGeoAudit, updateIssueStatus },
      busy,
    };
  }, [raw, source, mockReason, loading, error, refresh, runCrawl, runGeoAudit, updateIssueStatus, busy]);
}
