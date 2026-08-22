"use client";

import Link from "next/link";
import * as React from "react";
import { useRouter } from "next/navigation";

import { GapDrawer } from "@/components/intelligence/gap-drawer";
import { IntelligenceMetricSkeleton, IntelligenceMetricTile } from "@/components/intelligence/metric-tiles";
import { OpportunityCard } from "@/components/intelligence/opportunity-card";
import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { SearchGraph } from "@/components/intelligence/search-graph";
import { SourceChart } from "@/components/intelligence/source-chart";
import { SourceDrawer } from "@/components/intelligence/source-drawer";
import { useGraphView } from "@/components/intelligence/use-graph-view";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { useProject } from "@/components/project-provider";
import type { SourceRow } from "@/lib/intelligence/types";
import type { CitationGap } from "@ai-search-growth-os/types";
import { Button } from "@ai-search-growth-os/ui";

export default function AiIntelligenceOverviewPage() {
  const intel = useProjectIntelligence();
  const { current } = useProject();
  const router = useRouter();
  const loading = intel.loading || intel.projectLoading;
  const [openGap, setOpenGap] = React.useState<CitationGap | null>(null);
  const [openSource, setOpenSource] = React.useState<SourceRow | null>(null);
  const graph = useGraphView(current?.id ?? null, intel.source === "api", intel.raw?.graph ?? null, intel.windowRange);
  const sourceTypes = React.useMemo(() => [...new Set(intel.sources.map((s) => s.sourceType))].sort(), [intel.sources]);
  const selectSource = (id: string) => {
    const row = intel.sources.find((s) => s.sourceDomainId === id);
    if (row) setOpenSource(row);
  };
  const liveGap = (id: string) => intel.gaps.find((g) => g.id === id) ?? intel.opportunities.find((o) => o.gap.id === id)?.gap ?? null;

  return (
    <IntelligencePageFrame
      intel={intel}
      title="Citation Intelligence"
      description="Which sources AI engines cite when answering your prompts, how often those citations relate to you versus competitors, and where the gaps are. All numbers are counts of observed citations."
    >
      <section aria-label="Metrics" className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {loading ? Array.from({ length: 5 }, (_, i) => <IntelligenceMetricSkeleton key={i} />) : intel.metrics.map((m) => <IntelligenceMetricTile key={m.key} metric={m} />)}
      </section>

      <div className="mb-6 grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <SourceChart items={intel.topSources} loading={loading} onSelect={selectSource} />
        </div>
        <section aria-label="Citation gaps" className="lg:col-span-3">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">Where competitors are winning</h2>
              <p className="text-muted-foreground text-xs">Sources that cite competitors more than you. A citation there would not guarantee better AI visibility — it makes it possible.</p>
            </div>
            <Link href="/app/ai-intelligence/citation-gaps" className="text-primary shrink-0 text-sm underline-offset-4 hover:underline">
              All gaps
            </Link>
          </div>
          {loading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {Array.from({ length: 2 }, (_, i) => (
                <IntelligenceMetricSkeleton key={i} />
              ))}
            </div>
          ) : intel.opportunities.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-start gap-2 rounded-xl border border-dashed p-5 text-sm">
              <p>{intel.gapSummary?.data.note ?? "No citation gaps identified yet."}</p>
              {intel.source === "api" && (
                <Button size="sm" variant="outline" onClick={() => void intel.actions.analyzeGaps()} disabled={intel.busy === "analyze"}>
                  {intel.busy === "analyze" ? "Analysing…" : "Analyse citation gaps"}
                </Button>
              )}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {intel.opportunities.slice(0, 4).map((o) => (
                <OpportunityCard key={o.gap.id} card={o} onOpen={(id) => setOpenGap(liveGap(id))} />
              ))}
            </div>
          )}
        </section>
      </div>

      <SearchGraph
        view={graph.view}
        loading={loading || graph.loading}
        competitors={intel.competitorNames}
        providers={intel.providerKeys}
        sourceTypes={sourceTypes}
        filters={graph.filters}
        onFilter={graph.onFilter}
        onSelectSource={(id) => {
          const row = intel.sources.find((s) => s.sourceDomainId === id);
          if (row) setOpenSource(row);
          else router.push("/app/ai-intelligence/sources");
        }}
      />
      {graph.error && <p className="text-destructive mt-2 text-sm">{graph.error}</p>}

      <GapDrawer
        gap={openGap}
        brandName={intel.brandName}
        projectId={current?.id ?? null}
        live={intel.source === "api"}
        mockCitations={intel.raw?.citations ?? []}
        busy={intel.busy === "gap"}
        onUpdate={async (id, body) => {
          await intel.actions.updateGap(id, body);
          setOpenGap((g) => (g ? { ...g, ...body, note: body.note === undefined ? g.note : body.note, status: body.status ?? g.status } : g));
        }}
        onClose={() => setOpenGap(null)}
      />
      <SourceDrawer row={openSource} projectId={current?.id ?? null} range={intel.windowRange} live={intel.source === "api"} mockCitations={intel.raw?.citations ?? []} onClose={() => setOpenSource(null)} />
    </IntelligencePageFrame>
  );
}
