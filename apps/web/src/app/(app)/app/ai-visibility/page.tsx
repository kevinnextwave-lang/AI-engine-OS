"use client";

import * as React from "react";

import { AiInsightCard } from "@/components/ai-insight-card";
import { MetricAction } from "@/components/metric-action";
import { competitorGapInsight } from "@/lib/ai-insights";
import { CompetitorTable } from "@/components/visibility/competitor-table";
import { EngineTable } from "@/components/visibility/engine-table";
import { MetricTile, MetricTileSkeleton } from "@/components/visibility/metric-tile";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { PromptTable } from "@/components/visibility/prompt-table";
import { ResponseDrawer } from "@/components/visibility/response-drawer";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import { SectionHeader } from "@/components/shell/section-header";
import type { ChartMode, PromptPerformanceRow } from "@/lib/visibility/types";

export default function AiVisibilityOverviewPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("overall");
  const [openPrompt, setOpenPrompt] = React.useState<PromptPerformanceRow | null>(null);

  // Sparkline data: the measured overall-score buckets (real responses only).
  const scoreSpark = React.useMemo(() => {
    const points = vis.chart.overall[0]?.points ?? [];
    const values = points.map((p) => p.value).filter((v): v is number => v != null);
    return values.length >= 2 ? values : undefined;
  }, [vis.chart.overall]);

  const ahead = vis.competitorsAhead;
  const summaryLine = loading
    ? null
    : vis.competitorsConfigured === 0
      ? "Add competitors to see who is mentioned more often than you."
      : ahead.length === 0
        ? `No configured competitor is mentioned more often than ${vis.brandName} in this period.`
        : `${ahead.length} competitor${ahead.length === 1 ? " is" : "s are"} mentioned more often than ${vis.brandName}: ${ahead
            .slice(0, 3)
            .map((c) => `${c.name} (${c.mentionRate}%)`)
            .join(", ")}.`;

  return (
    <VisibilityPageFrame
      vis={vis}
      title="AI Visibility"
      description="How often AI engines mention, recommend and cite your brand when answering your prompts. Measured from real AI responses; the score is our own methodology."
    >
      <section aria-label="Primary metrics" className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {loading
          ? Array.from({ length: 6 }, (_, i) => <MetricTileSkeleton key={i} />)
          : vis.metrics.map((m) => (
              <MetricTile
                key={m.key}
                metric={m}
                emphasis={m.key === "score"}
                // Real measured score history from the same series the chart shows.
                spark={m.key === "score" ? scoreSpark : undefined}
                action={m.key === "score" ? <MetricAction href="/app/ai-visibility/trends">View trends</MetricAction> : undefined}
              />
            ))}
      </section>

      {!loading && (
        <div className="mb-6">
          <AiInsightCard
            insight={competitorGapInsight({
              brandName: vis.brandName,
              competitors: vis.competitors,
              competitorsAhead: vis.competitorsAhead,
              sampleSize: vis.quality?.sampleSize ?? 0,
            })}
            href="/app/ai-visibility/competitors"
          />
        </div>
      )}

      <div className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} />
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <section aria-label="AI engine comparison">
          <SectionHeader title="By AI engine" hint="AI Visibility Score per provider, same period." href="/app/ai-visibility/ai-engines" />
          <EngineTable rows={vis.engines} loading={loading} />
        </section>
        <section aria-label="Competitor comparison">
          <SectionHeader
            title="Who is beating you"
            hint="Measured mention rate in AI responses — share of responses naming each brand."
            href="/app/ai-visibility/competitors"
          />
          {summaryLine && <p className="mb-3 text-sm">{summaryLine}</p>}
          <CompetitorTable rows={vis.competitors} loading={loading} competitorsConfigured={vis.competitorsConfigured} />
        </section>
      </div>

      <section aria-label="Prompt performance">
        <SectionHeader title="Why — prompt performance" hint="Click a prompt to read the actual AI answers." href="/app/ai-visibility/prompts" />
        <PromptTable rows={vis.prompts} loading={loading} onOpen={setOpenPrompt} limit={8} />
      </section>

      <ResponseDrawer prompt={openPrompt} brandName={vis.brandName} live={vis.source === "api"} onClose={() => setOpenPrompt(null)} />
    </VisibilityPageFrame>
  );
}
