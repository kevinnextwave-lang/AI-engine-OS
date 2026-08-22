"use client";

import * as React from "react";

import { api } from "@/lib/api";
import type { GraphView } from "@/lib/intelligence/types";
import type { GraphOverview } from "@ai-search-growth-os/types";

export interface GraphFilterState {
  competitor: string | null;
  sourceType: string | null;
  provider: string | null;
}

function toView(g: GraphOverview): GraphView {
  return { nodes: g.nodes, edges: g.edges, truncated: g.statistics.truncated };
}

/**
 * The graph for the visualisation. Without server-side filters it is the
 * already-loaded overview; with an engine or source-type filter it refetches
 * a filtered (still bounded) subgraph.
 */
export function useGraphView(projectId: string | null, live: boolean, base: GraphOverview | null, range: { start: string; end: string }) {
  const [filters, setFilters] = React.useState<GraphFilterState>({ competitor: null, sourceType: null, provider: null });
  const [fetched, setFetched] = React.useState<{ key: string; view: GraphView | null; error: string | null } | null>(null);
  const needsFetch = live && projectId !== null && (filters.sourceType !== null || filters.provider !== null);
  const key = `${projectId}|${range.start}|${range.end}|${filters.sourceType ?? ""}|${filters.provider ?? ""}`;

  React.useEffect(() => {
    if (!needsFetch || !projectId) return;
    let cancelled = false;
    api.intelligenceGraph
      .overview(projectId, { ...range, provider: filters.provider ?? undefined, source_type: filters.sourceType ?? undefined, top_sources: 14, top_prompts: 12, top_claims: 0 })
      .then((g) => !cancelled && setFetched({ key, view: toView(g), error: null }))
      .catch((err: unknown) => !cancelled && setFetched({ key, view: null, error: err instanceof Error ? err.message : "Request failed" }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, needsFetch]);

  const view: GraphView | null = needsFetch ? (fetched?.key === key ? fetched.view : null) : base ? toView(base) : null;
  const loading = needsFetch && fetched?.key !== key;
  const onFilter = React.useCallback((f: Partial<GraphFilterState>) => setFilters((prev) => ({ ...prev, ...f })), []);
  return { view, loading, filters, onFilter, error: needsFetch && fetched?.key === key ? fetched.error : null };
}
