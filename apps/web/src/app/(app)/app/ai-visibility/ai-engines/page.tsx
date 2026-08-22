"use client";

import * as React from "react";

import { EngineTable } from "@/components/visibility/engine-table";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { ChartMode } from "@/lib/visibility/types";

export default function AiEnginesPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("provider");
  return (
    <VisibilityPageFrame
      vis={vis}
      title="AI Engines"
      description="The same AI Visibility Score broken down by provider and model. Each row is measured only from that engine's responses."
    >
      <div className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} modes={["overall", "provider"]} />
      </div>
      <EngineTable rows={vis.engines} loading={loading} detailed />
    </VisibilityPageFrame>
  );
}
