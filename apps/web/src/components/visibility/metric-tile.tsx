import * as React from "react";

import { fmtChange, fmtValue } from "@/components/visibility/format";
import type { VisibilityMetric } from "@/lib/visibility/types";
import { MetricCard, MetricCardSkeleton, type MetricDelta, type MetricTone } from "@ai-search-growth-os/ui";

/** Score status at the shared 80/60 thresholds; visibility wording. */
function scoreStatus(value: number | null): { tone: MetricTone; label: string } {
  if (value == null) return { tone: "neutral", label: "Not measured" };
  if (value >= 80) return { tone: "success", label: "Strong" };
  if (value >= 60) return { tone: "caution", label: "Moderate" };
  return { tone: "warning", label: "Weak" };
}

/** Real previous-period change; null when no comparison data exists. */
function toDelta(metric: VisibilityMetric): MetricDelta | null {
  if (metric.change == null) return null;
  const better = metric.lowerIsBetter ? metric.change < 0 : metric.change > 0;
  const flat = Math.abs(metric.change) < (metric.unit === "position" ? 0.1 : 2);
  return {
    text: fmtChange(metric.change, metric.unit),
    direction: flat ? "flat" : metric.change > 0 ? "up" : "down",
    good: flat ? null : better,
    caption: "vs previous period",
  };
}

export function MetricTile({
  metric,
  emphasis = false,
  spark,
  action,
}: {
  metric: VisibilityMetric;
  emphasis?: boolean;
  /** Real score history for a sparkline (oldest first); omit when absent. */
  spark?: number[];
  action?: React.ReactNode;
}) {
  const isScore = metric.unit === "score";
  return (
    <MetricCard
      label={metric.label}
      value={metric.value == null ? "–" : fmtValue(metric.value, metric.unit)}
      unit={metric.value != null && isScore ? "/100" : undefined}
      status={isScore ? scoreStatus(metric.value) : undefined}
      delta={toDelta(metric)}
      spark={spark}
      meaning={metric.note}
      context={
        <>
          n = {metric.sampleSize} response{metric.sampleSize === 1 ? "" : "s"}
          {metric.change == null && (
            <> · {metric.value == null ? (metric.unavailableReason ?? "not enough data") : "no comparison available"}</>
          )}
        </>
      }
      action={action}
      size={emphasis ? "hero" : "default"}
      className={emphasis ? "border-primary/40 h-full" : "h-full"}
    />
  );
}

export function MetricTileSkeleton() {
  return <MetricCardSkeleton />;
}
