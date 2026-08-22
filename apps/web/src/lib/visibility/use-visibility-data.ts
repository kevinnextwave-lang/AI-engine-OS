"use client";

/**
 * Loads everything the AI Visibility section needs for one project + window
 * and derives the view models. Components consume the result only.
 *
 * Provenance is explicit: `source === "api"` means every dataset came from the
 * backend for the selected project; `source === "mock"` means bundled sample
 * data (no project selected, or the API unreachable). Never mixed. A selected
 * project with too little data is `empty`, never sample numbers.
 */

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import type {
  PromptRow,
  PromptSet,
  ProviderStatus,
  VisibilityByEngine,
  VisibilityByPrompt,
  VisibilityCompetitors,
  VisibilityOverview,
  VisibilityTrends,
  VisibilityWindow,
} from "@ai-search-growth-os/types";

import {
  competitorRows,
  competitorSeries,
  competitorsAhead,
  dataQuality,
  engineRows,
  overallSeries,
  primaryMetrics,
  promptRows,
  providerSeries,
  trendWindows,
} from "./mappers";
import {
  MOCK_BRAND,
  MOCK_BY_ENGINE,
  MOCK_BY_PROMPT,
  MOCK_COMPETITORS,
  MOCK_OVERVIEW,
  MOCK_PROMPT_ROWS,
  MOCK_TRENDS,
} from "./mock";
import type {
  ChartSeries,
  CompetitorShareRow,
  DataQualitySummary,
  DataSource,
  EngineRow,
  PromptPerformanceRow,
  TrendWindowRow,
  VisibilityMetric,
} from "./types";

interface RawData {
  overview: VisibilityOverview;
  trends: VisibilityTrends;
  byEngine: VisibilityByEngine;
  byPrompt: VisibilityByPrompt;
  competitors: VisibilityCompetitors;
  promptSets: PromptSet[];
  prompts: PromptRow[];
  providers: ProviderStatus[];
}

export interface VisibilityData {
  source: DataSource;
  mockReason: string | null;
  loading: boolean;
  error: string | null;
  /** A project is selected, data loaded, and no eligible responses exist for the window. */
  empty: boolean;
  window: VisibilityWindow;
  setWindow: (w: VisibilityWindow) => void;
  brandName: string;
  quality: DataQualitySummary | null;
  metrics: VisibilityMetric[];
  chart: { overall: ChartSeries[]; provider: ChartSeries[]; competitor: ChartSeries[] };
  engines: EngineRow[];
  competitors: CompetitorShareRow[];
  competitorsAhead: CompetitorShareRow[];
  competitorsConfigured: number;
  prompts: PromptPerformanceRow[];
  trendWindows: TrendWindowRow[];
  raw: RawData | null;
  /** Providers the server can run (never exposes credentials). */
  configuredProviders: string[];
  /** First prompt set with active prompts, if any — target of "Run Prompt Set". */
  runnableSet: PromptSet | null;
  actions: { refresh: () => void; runPromptSet: () => Promise<void> };
  busy: "run" | null;
  /** Set after a run was queued so the page can explain what happens next. */
  runNotice: string | null;
}

interface Loaded {
  projectId: string;
  window: VisibilityWindow;
  raw: RawData | null;
  source: DataSource;
  mockReason: string | null;
  error: string | null;
}

const MOCK_RAW: RawData = {
  overview: MOCK_OVERVIEW,
  trends: MOCK_TRENDS,
  byEngine: MOCK_BY_ENGINE,
  byPrompt: MOCK_BY_PROMPT,
  competitors: MOCK_COMPETITORS,
  promptSets: [],
  prompts: MOCK_PROMPT_ROWS,
  providers: [],
};

async function loadFromApi(projectId: string, window: VisibilityWindow): Promise<RawData> {
  const [overview, trends, byEngine, byPrompt, competitors, sets, providers] = await Promise.all([
    api.visibility.overview(projectId, window),
    api.visibility.trends(projectId),
    api.visibility.byEngine(projectId, window),
    api.visibility.byPrompt(projectId, window),
    api.visibility.competitors(projectId, window),
    api.prompts.listSets(projectId),
    api.ai.providers(),
  ]);
  const active = sets.items.filter((s) => s.status !== "archived");
  const prompts = (await Promise.all(active.map((s) => api.prompts.list(s.id)))).flatMap((r) => r.items);
  return { overview, trends, byEngine, byPrompt, competitors, promptSets: active, prompts, providers: providers.items };
}

function isNetworkFailure(err: unknown): boolean {
  return !(err instanceof ApiError);
}

const NO_PROJECT: Omit<Loaded, "projectId" | "window"> = {
  raw: MOCK_RAW,
  source: "mock",
  mockReason: "No project selected — showing sample data.",
  error: null,
};

export function useVisibilityData(projectId: string | null, brandName: string | null): VisibilityData {
  const [window, setWindow] = React.useState<VisibilityWindow>("30d");
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [version, setVersion] = React.useState(0);
  const [busy, setBusy] = React.useState<VisibilityData["busy"]>(null);
  const [runNotice, setRunNotice] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    loadFromApi(projectId, window)
      .then((raw) => {
        if (!cancelled) setLoaded({ projectId, window, raw, source: "api", mockReason: null, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isNetworkFailure(err)) {
          setLoaded({
            projectId,
            window,
            raw: MOCK_RAW,
            source: "mock",
            mockReason: "The API could not be reached — showing sample data.",
            error: null,
          });
        } else {
          setLoaded({
            projectId,
            window,
            raw: null,
            source: "api",
            mockReason: null,
            error: err instanceof Error ? err.message : "Request failed",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, window, version]);

  const current: Omit<Loaded, "projectId" | "window"> | null = !projectId
    ? NO_PROJECT
    : loaded?.projectId === projectId && loaded.window === window
      ? loaded
      : null;
  const loading = current === null;
  const raw = current?.raw ?? null;
  const source: DataSource = current?.source ?? "api";
  const mockReason = current?.mockReason ?? null;
  const error = current?.error ?? null;

  const refresh = React.useCallback(() => setVersion((v) => v + 1), []);

  const configuredProviders = React.useMemo(
    () => (raw?.providers ?? []).filter((p) => p.configured).map((p) => p.key),
    [raw],
  );
  const runnableSet = React.useMemo(
    () => raw?.promptSets.find((s) => s.active_prompt_count > 0) ?? null,
    [raw],
  );

  const runPromptSet = React.useCallback(async () => {
    if (!projectId || source !== "api" || !runnableSet || configuredProviders.length === 0) return;
    setBusy("run");
    try {
      const batch = await api.prompts.run(runnableSet.id, { providers: configuredProviders });
      setRunNotice(
        `Queued ${batch.total_runs} prompt runs for “${runnableSet.name}”. Results appear here once responses are collected and parsed.`,
      );
      refresh();
    } finally {
      setBusy(null);
    }
  }, [projectId, source, runnableSet, configuredProviders, refresh]);

  return React.useMemo<VisibilityData>(() => {
    const brand = source === "mock" ? MOCK_BRAND : (brandName ?? "Your brand");
    const empty = source === "api" && raw !== null && raw.overview.current.data_quality.sample_size === 0;
    const competitors = raw ? competitorRows(raw.competitors, brand) : [];
    return {
      source,
      mockReason,
      loading,
      error,
      empty,
      window,
      setWindow,
      brandName: brand,
      quality: raw ? dataQuality(raw.overview.current) : null,
      metrics: raw ? primaryMetrics(raw.overview) : [],
      chart: raw
        ? {
            overall: overallSeries(raw.trends),
            provider: providerSeries(raw.trends),
            competitor: competitorSeries(raw.trends, brand),
          }
        : { overall: [], provider: [], competitor: [] },
      engines: raw ? engineRows(raw.byEngine) : [],
      competitors,
      competitorsAhead: competitorsAhead(competitors),
      competitorsConfigured: raw?.overview.competitors_configured ?? 0,
      prompts: raw ? promptRows(raw.byPrompt, raw.prompts) : [],
      trendWindows: raw ? trendWindows(raw.trends) : [],
      raw,
      configuredProviders,
      runnableSet,
      actions: { refresh, runPromptSet },
      busy,
      runNotice,
    };
  }, [
    source,
    mockReason,
    loading,
    error,
    window,
    brandName,
    raw,
    configuredProviders,
    runnableSet,
    refresh,
    runPromptSet,
    busy,
    runNotice,
  ]);
}
