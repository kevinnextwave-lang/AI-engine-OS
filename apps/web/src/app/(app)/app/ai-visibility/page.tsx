"use client";

import Link from "next/link";
import * as React from "react";

import { CompetitorTable } from "@/components/visibility/competitor-table";
import { EngineTable } from "@/components/visibility/engine-table";
import { MetricTile, MetricTileSkeleton } from "@/components/visibility/metric-tile";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { PromptTable } from "@/components/visibility/prompt-table";
import { ResponseDrawer } from "@/components/visibility/response-drawer";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { ChartMode, PromptPerformanceRow } from "@/lib/visibility/types";

function SectionTitle({ title, hint, href }: { title: string; hint?: string; href?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </div>
      {href && (
        <Link href={href} className="text-primary shrink-0 text-sm underline-offset-4 hover:underline">
          Open
        </Link>
      )}
    </div>
  );
}

export default function AiVisibilityOverviewPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("overall");
  const [openPrompt, setOpenPrompt] = React.useState<PromptPerformanceRow | null>(null);

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
      <section aria-label="Primary metrics" className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {loading
          ? Array.from({ length: 6 }, (_, i) => <MetricTileSkeleton key={i} />)
          : vis.metrics.map((m) => <MetricTile key={m.key} metric={m} emphasis={m.key === "score"} />)}
      </section>

      <div className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} />
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <section aria-label="AI engine comparison">
          <SectionTitle title="By AI engine" hint="AI Visibility Score per provider, same period." href="/app/ai-visibility/ai-engines" />
          <EngineTable rows={vis.engines} loading={loading} />
        </section>
        <section aria-label="Competitor comparison">
          <SectionTitle
            title="Who is beating you"
            hint="Measured mention rate in AI responses — share of responses naming each brand."
            href="/app/ai-visibility/competitors"
          />
          {summaryLine && <p className="mb-3 text-sm">{summaryLine}</p>}
          <CompetitorTable rows={vis.competitors} loading={loading} competitorsConfigured={vis.competitorsConfigured} />
        </section>
      </div>

      <section aria-label="Prompt performance">
        <SectionTitle title="Why — prompt performance" hint="Click a prompt to read the actual AI answers." href="/app/ai-visibility/prompts" />
        <PromptTable rows={vis.prompts} loading={loading} onOpen={setOpenPrompt} limit={8} />
      </section>

      <ResponseDrawer prompt={openPrompt} brandName={vis.brandName} live={vis.source === "api"} onClose={() => setOpenPrompt(null)} />
    </VisibilityPageFrame>
  );
}
