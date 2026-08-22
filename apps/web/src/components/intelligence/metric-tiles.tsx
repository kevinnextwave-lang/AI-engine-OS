import type { IntelligenceMetric } from "@/lib/intelligence/types";
import { Card, CardContent, Skeleton } from "@ai-search-growth-os/ui";

export function IntelligenceMetricTile({ metric }: { metric: IntelligenceMetric }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex flex-col gap-1.5 px-4">
        <p className="text-muted-foreground text-sm font-medium" title={metric.note}>
          {metric.label}
        </p>
        <p className="text-3xl font-semibold tabular-nums">
          {metric.value == null ? <span className="text-muted-foreground">–</span> : metric.unit === "percent" ? `${metric.value}%` : metric.value.toLocaleString()}
        </p>
        <p className="text-muted-foreground line-clamp-2 text-xs">{metric.note}</p>
      </CardContent>
    </Card>
  );
}

export function IntelligenceMetricSkeleton() {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex flex-col gap-2 px-4">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-9 w-16" />
        <Skeleton className="h-3 w-40" />
      </CardContent>
    </Card>
  );
}
