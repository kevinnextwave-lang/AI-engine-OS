import { MetricAction } from "@/components/metric-action";
import type { IntelligenceMetric } from "@/lib/intelligence/types";
import { MetricCard, MetricCardSkeleton } from "@ai-search-growth-os/ui";

/** Where each metric's detail view lives (only where a natural one exists). */
const METRIC_HREF: Partial<Record<IntelligenceMetric["key"], string>> = {
  citations: "/app/ai-intelligence/citations",
  sources: "/app/ai-intelligence/sources",
  gaps: "/app/ai-intelligence/citation-gaps",
};

export function IntelligenceMetricTile({ metric }: { metric: IntelligenceMetric }) {
  const href = METRIC_HREF[metric.key];
  return (
    <MetricCard
      label={metric.label}
      value={
        metric.value == null
          ? "–"
          : metric.unit === "percent"
            ? metric.value
            : metric.value.toLocaleString()
      }
      unit={metric.value != null && metric.unit === "percent" ? "%" : undefined}
      meaning={metric.note}
      action={href ? <MetricAction href={href}>View details</MetricAction> : undefined}
      className="h-full"
    />
  );
}

export function IntelligenceMetricSkeleton() {
  return <MetricCardSkeleton />;
}
