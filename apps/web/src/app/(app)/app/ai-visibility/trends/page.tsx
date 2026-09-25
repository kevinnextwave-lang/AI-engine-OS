"use client";

import * as React from "react";

import { ConfidenceBadge } from "@/components/visibility/confidence";
import { fmtChange, fmtValue } from "@/components/visibility/format";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { ChartMode } from "@/lib/visibility/types";
import { MetricCard, MetricCardSkeleton, type MetricTone } from "@ai-search-growth-os/ui";

const TREND_META: Record<string, { label: string; tone: MetricTone }> = {
  up: { label: "Improving", tone: "success" },
  down: { label: "Declining", tone: "warning" },
  flat: { label: "Stable", tone: "neutral" },
  unavailable: { label: "Not comparable", tone: "neutral" },
};

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
          ? Array.from({ length: 3 }, (_, i) => <MetricCardSkeleton key={i} />)
          : vis.trendWindows.map((w) => {
              const meta = TREND_META[w.trend] ?? TREND_META.unavailable!;
              return (
                <MetricCard
                  key={w.window}
                  label={`Last ${w.label}`}
                  value={fmtValue(w.current, "score")}
                  unit={w.current != null ? "/100" : undefined}
                  status={{ tone: meta.tone, label: meta.label }}
                  delta={
                    w.change != null
                      ? {
                          text: fmtChange(w.change, "score"),
                          direction: w.trend === "up" ? "up" : w.trend === "down" ? "down" : "flat",
                          good: w.trend === "up" ? true : w.trend === "down" ? false : null,
                          caption: `vs previous ${w.label}`,
                        }
                      : null
                  }
                  meaning={
                    w.change == null && w.reason
                      ? w.reason.replace(/^insufficient data/, "Not enough responses")
                      : `Measured AI Visibility Score over the last ${w.label}.`
                  }
                  context={
                    <span className="flex items-center gap-2">
                      <ConfidenceBadge
                        sufficiency={
                          w.currentSampleSize >= 50
                            ? "high"
                            : w.currentSampleSize >= 20
                              ? "moderate"
                              : w.currentSampleSize >= 5
                                ? "low"
                                : "insufficient"
                        }
                        sampleSize={w.currentSampleSize}
                      />
                      <span className="tabular-nums">
                        n = {w.currentSampleSize} now · {w.previousSampleSize} before
                      </span>
                    </span>
                  }
                  className="h-full"
                />
              );
            })}
      </section>
      <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} />
    </VisibilityPageFrame>
  );
}
