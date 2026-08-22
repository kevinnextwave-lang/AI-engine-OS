"use client";

/**
 * Loads the Citation Intelligence datasets for one project + window and
 * derives the view models. Components consume the result only.
 *
 * Provenance is explicit (`source: "api" | "mock"`, never mixed). A selected
 * project with no citations in the window is `empty` — never sample numbers.
 */

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import type {
  CitationGap,
  CitationGapSummary,
  CitationListItem,
  GapStatus,
  GraphClaimsResponse,
  GraphOverview,
  GraphSourcesResponse,
  PromptSet,
  ProviderStatus,
} from "@ai-search-growth-os/types";

import { claimRows, opportunityCard, overviewMetrics, sourceRows, topSources } from "./mappers";
import {
  MOCK_BRAND,
  MOCK_CITATIONS,
  MOCK_CLAIMS,
  MOCK_GAPS,
  MOCK_GAP_SUMMARY,
  MOCK_GRAPH,
  MOCK_SOURCES,
} from "./mock";
import type { ClaimRow, DataSource, IntelligenceMetric, OpportunityCard, SourceRow, TopSourceBar } from "./types";

export type IntelligenceWindow = "30d" | "90d" | "180d";
const WINDOW_DAYS: Record<IntelligenceWindow, number> = { "30d": 30, "90d": 90, "180d": 180 };

interface RawData {
  graph: GraphOverview;
  sources: GraphSourcesResponse;
  claims: GraphClaimsResponse;
  gaps: CitationGap[];
  gapSummary: CitationGapSummary;
  citations: CitationListItem[];
  citationsTotal: number;
  promptSets: PromptSet[];
  providers: ProviderStatus[];
}

export interface IntelligenceData {
  source: DataSource;
  mockReason: string | null;
  loading: boolean;
  error: string | null;
  empty: boolean;
  window: IntelligenceWindow;
  setWindow: (w: IntelligenceWindow) => void;
  windowRange: { start: string; end: string };
  brandName: string;
  raw: RawData | null;
  metrics: IntelligenceMetric[];
  topSources: TopSourceBar[];
  opportunities: OpportunityCard[];
  sources: SourceRow[];
  claims: ClaimRow[];
  gaps: CitationGap[];
  gapSummary: CitationGapSummary | null;
  competitorNames: string[];
  providerKeys: string[];
  configuredProviders: string[];
  runnableSet: PromptSet | null;
  actions: {
    refresh: () => void;
    runPromptSet: () => Promise<void>;
    analyzeGaps: () => Promise<void>;
    updateGap: (gapId: string, body: { status?: GapStatus; note?: string | null }) => Promise<void>;
  };
  busy: "run" | "analyze" | "gap" | null;
  runNotice: string | null;
}

interface Loaded {
  projectId: string;
  window: IntelligenceWindow;
  raw: RawData | null;
  source: DataSource;
  mockReason: string | null;
  error: string | null;
}

const MOCK_RAW: RawData = {
  graph: MOCK_GRAPH,
  sources: MOCK_SOURCES,
  claims: MOCK_CLAIMS,
  gaps: MOCK_GAPS,
  gapSummary: MOCK_GAP_SUMMARY,
  citations: MOCK_CITATIONS,
  citationsTotal: MOCK_CITATIONS.length,
  promptSets: [],
  providers: [],
};

function rangeFor(window: IntelligenceWindow): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - WINDOW_DAYS[window] * 86_400_000);
  return { start: start.toISOString(), end: end.toISOString() };
}

async function loadFromApi(projectId: string, window: IntelligenceWindow): Promise<RawData> {
  const range = rangeFor(window);
  const [graph, sources, claims, gapList, gapSummary, citations, sets, providers] = await Promise.all([
    api.intelligenceGraph.overview(projectId, { ...range, top_sources: 12, top_prompts: 12, top_claims: 0 }),
    api.intelligenceGraph.sources(projectId, { ...range, view: "top", limit: 200 }),
    api.intelligenceGraph.claims(projectId, { ...range, min_occurrences: 2, limit: 200 }),
    api.citationGaps.list(projectId, { limit: 200 }),
    api.citationGaps.summary(projectId),
    api.citations.list(projectId, { ...range, limit: 200 }),
    api.prompts.listSets(projectId),
    api.ai.providers(),
  ]);
  return {
    graph,
    sources,
    claims,
    gaps: gapList.items,
    gapSummary,
    citations: citations.items,
    citationsTotal: citations.total,
    promptSets: sets.items.filter((s) => s.status !== "archived"),
    providers: providers.items,
  };
}

const NO_PROJECT: Omit<Loaded, "projectId" | "window"> = {
  raw: MOCK_RAW,
  source: "mock",
  mockReason: "No project selected — showing sample data.",
  error: null,
};

export function useIntelligenceData(projectId: string | null, brandName: string | null): IntelligenceData {
  const [window, setWindow] = React.useState<IntelligenceWindow>("90d");
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [version, setVersion] = React.useState(0);
  const [busy, setBusy] = React.useState<IntelligenceData["busy"]>(null);
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
        if (!(err instanceof ApiError)) {
          setLoaded({ projectId, window, raw: MOCK_RAW, source: "mock", mockReason: "The API could not be reached — showing sample data.", error: null });
        } else {
          setLoaded({ projectId, window, raw: null, source: "api", mockReason: null, error: err.message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, window, version]);

  const current = !projectId ? NO_PROJECT : loaded?.projectId === projectId && loaded.window === window ? loaded : null;
  const loading = current === null;
  const raw = current?.raw ?? null;
  const source: DataSource = current?.source ?? "api";
  const refresh = React.useCallback(() => setVersion((v) => v + 1), []);

  const configuredProviders = React.useMemo(() => (raw?.providers ?? []).filter((p) => p.configured).map((p) => p.key), [raw]);
  const runnableSet = React.useMemo(() => raw?.promptSets.find((s) => s.active_prompt_count > 0) ?? null, [raw]);

  const runPromptSet = React.useCallback(async () => {
    if (!projectId || source !== "api" || !runnableSet || configuredProviders.length === 0) return;
    setBusy("run");
    try {
      const batch = await api.prompts.run(runnableSet.id, { providers: configuredProviders });
      setRunNotice(`Queued ${batch.total_runs} prompt runs for “${runnableSet.name}”. Citations appear here once responses are collected and parsed.`);
      refresh();
    } finally {
      setBusy(null);
    }
  }, [projectId, source, runnableSet, configuredProviders, refresh]);

  const analyzeGaps = React.useCallback(async () => {
    if (!projectId || source !== "api") return;
    setBusy("analyze");
    try {
      await api.citationGaps.analyze(projectId, WINDOW_DAYS[window]);
      refresh();
    } finally {
      setBusy(null);
    }
  }, [projectId, source, window, refresh]);

  const updateGap = React.useCallback(
    async (gapId: string, body: { status?: GapStatus; note?: string | null }) => {
      if (source !== "api") return;
      setBusy("gap");
      try {
        const updated = await api.citationGaps.update(gapId, body);
        setLoaded((prev) =>
          prev && prev.raw
            ? { ...prev, raw: { ...prev.raw, gaps: prev.raw.gaps.map((g) => (g.id === updated.id ? updated : g)) } }
            : prev,
        );
      } finally {
        setBusy(null);
      }
    },
    [source],
  );

  return React.useMemo<IntelligenceData>(() => {
    const brand = source === "mock" ? MOCK_BRAND : (brandName ?? "Your brand");
    const empty = source === "api" && raw !== null && raw.graph.statistics.citations === 0;
    const gaps = raw?.gaps ?? [];
    const competitorNames = raw
      ? [...new Set(raw.graph.nodes.filter((n) => n.type === "competitor").map((n) => n.label))].sort()
      : [];
    const providerKeys = raw ? [...new Set(raw.citations.map((c) => c.provider_key).filter((p): p is string => !!p))].sort() : [];
    return {
      source,
      mockReason: current?.mockReason ?? null,
      loading,
      error: current?.error ?? null,
      empty,
      window,
      setWindow,
      windowRange: raw ? raw.graph.window : rangeFor(window),
      brandName: brand,
      raw,
      metrics: overviewMetrics(raw?.graph ?? null, raw?.gapSummary ?? null),
      topSources: raw ? topSources(raw.sources.items) : [],
      opportunities: (raw?.gapSummary.top_opportunities ?? []).map((g) => opportunityCard(g, brand)),
      sources: raw ? sourceRows(raw.sources.items, gaps) : [],
      claims: raw ? claimRows(raw.claims.items) : [],
      gaps,
      gapSummary: raw?.gapSummary ?? null,
      competitorNames,
      providerKeys,
      configuredProviders,
      runnableSet,
      actions: { refresh, runPromptSet, analyzeGaps, updateGap },
      busy,
      runNotice,
    };
  }, [source, current, loading, window, brandName, raw, configuredProviders, runnableSet, refresh, runPromptSet, analyzeGaps, updateGap, busy, runNotice]);
}
