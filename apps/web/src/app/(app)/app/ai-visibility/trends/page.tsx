"use client";

import * as React from "react";

import { ConfidenceBadge } from "@/components/visibility/confidence";
import { fmtChange, fmtValue } from "@/components/visibility/format";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { ChartMode } from "@/lib/visibility/types";
import { Card, CardContent, Skeleton } from "@ai-search-growth-os/ui";

const TREND_LABEL = { up: "Improving", down: "Declining", flat: "Stable", unavailable: "Not comparable" } as const;

export default function TrendsPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("overall");
  return (
    <VisibilityPageFrame
      vis={vis}
      title="Trends"
      description="AI Visibility Score now versus the preceding period of the same length. A change under 2 points is reported as stable."
    >
      <section aria-label="Period comparisons" className="mb-6 grid gap-3 md:grid-cols-3">
        {loading
          ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-32" />)
          : vis.trendWindows.map((w) => (
              <Card key={w.window} className="gap-2 py-4">
                <CardContent className="flex flex-col gap-1.5 px-4">
                  <p className="text-muted-foreground text-sm font-medium">Last {w.label}</p>
                  <p className="text-3xl font-semibold tabular-nums">
                    {fmtValue(w.current, "score")}
                    {w.current != null && <span className="text-muted-foreground ml-1 text-base font-normal">/100</span>}
                  </p>
                  <p className="text-sm">
                    {TREND_LABEL[w.trend]}
                    {w.change != null && <span className="text-muted-foreground tabular-nums"> · {fmtChange(w.change, "score")} vs previous {w.label}</span>}
                    {w.change == null && w.reason && <span className="text-muted-foreground"> · {w.reason.replace(/^insufficient data/, "not enough responses")}</span>}
                  </p>
                  <div className="flex items-center gap-2">
                    <ConfidenceBadge sufficiency={w.currentSampleSize >= 50 ? "high" : w.currentSampleSize >= 20 ? "moderate" : w.currentSampleSize >= 5 ? "low" : "insufficient"} sampleSize={w.currentSampleSize} />
                    <span className="text-muted-foreground text-xs tabular-nums">
                      n = {w.currentSampleSize} now · {w.previousSampleSize} before
                    </span>
                  </div>
                </CardContent>
              </Card>
            ))}
      </section>
      <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} />
    </VisibilityPageFrame>
  );
}
