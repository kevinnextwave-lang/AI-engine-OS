"use client";

import * as React from "react";

import { CompetitorTable } from "@/components/visibility/competitor-table";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { ChartMode } from "@/lib/visibility/types";

export default function CompetitorsPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("competitor");
  const competitive = vis.metrics.find((m) => m.key === "competitive_share") ?? null;
  return (
    <VisibilityPageFrame
      vis={vis}
      title="Competitors"
      description="Measured AI-response visibility: the share of answers that name each configured competitor versus your brand. Brands you have not configured are not compared and never lower your score."
    >
      {!loading && competitive && (
        <p className="mb-4 text-sm">
          Competitive share:{" "}
          <strong className="tabular-nums">{competitive.value == null ? "not available" : `${competitive.value}/100`}</strong>
          {competitive.value == null && competitive.unavailableReason && (
            <span className="text-muted-foreground"> — {competitive.unavailableReason}</span>
          )}
          {competitive.value != null && <span className="text-muted-foreground"> — 100 means you are mentioned at least as often as the top competitor.</span>}
        </p>
      )}
      <div className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} modes={["overall", "competitor"]} />
      </div>
      <CompetitorTable rows={vis.competitors} loading={loading} detailed competitorsConfigured={vis.competitorsConfigured} />
    </VisibilityPageFrame>
  );
}
