"use client";

import * as React from "react";

import { AiInsightCard } from "@/components/ai-insight-card";
import { EngineTable } from "@/components/visibility/engine-table";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import { engineZeroInsight } from "@/lib/ai-insights";
import type { ChartMode } from "@/lib/visibility/types";

export default function AiEnginesPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("provider");
  // Only a genuinely MEASURED zero (n > 0, score === 0) produces the
  // recommendation; unavailable scores (null) never do, and while loading
  // the card simply isn't rendered.
  const zeroInsight = loading ? null : engineZeroInsight(vis.engines, vis.brandName);
  return (
    <VisibilityPageFrame
      vis={vis}
      title="AI Engines"
      description="The same AI Visibility Score broken down by provider and model. Each row is measured only from that engine's responses."
    >
      {zeroInsight && (
        <div className="mb-6">
          <AiInsightCard insight={zeroInsight} href="/app/ai-visibility/prompts?filter=missing" />
        </div>
      )}
      <div className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} modes={["overall", "provider"]} />
      </div>
      <EngineTable rows={vis.engines} loading={loading} detailed />
    </VisibilityPageFrame>
  );
}
