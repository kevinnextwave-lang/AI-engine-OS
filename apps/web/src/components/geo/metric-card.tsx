import type { GeoMetric } from "@/lib/geo/types";
import { Card, CardContent, Progress, Skeleton } from "@ai-search-growth-os/ui";

function tone(value: number | null): string {
  if (value == null) return "bg-muted-foreground/40";
  if (value >= 80) return "bg-emerald-600";
  if (value >= 60) return "bg-amber-500";
  return "bg-orange-600";
}

export function MetricCard({ metric }: { metric: GeoMetric }) {
  return (
    <Card className="gap-3 py-5">
      <CardContent className="flex flex-col gap-3 px-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-muted-foreground text-sm font-medium">{metric.label}</p>
        </div>
        <p className="text-3xl font-semibold tabular-nums">
          {metric.value == null ? <span className="text-muted-foreground">–</span> : Math.round(metric.value)}
          {metric.value != null && <span className="text-muted-foreground ml-1 text-base font-normal">/100</span>}
        </p>
        <Progress value={metric.value ?? 0} indicatorClassName={tone(metric.value)} aria-label={metric.label} />
        <p className="text-muted-foreground text-xs" title={metric.description}>
          {metric.basis}
        </p>
      </CardContent>
    </Card>
  );
}

export function MetricCardSkeleton() {
  return (
    <Card className="gap-3 py-5">
      <CardContent className="flex flex-col gap-3 px-5">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-20" />
        <Skeleton className="h-2 w-full" />
        <Skeleton className="h-3 w-40" />
      </CardContent>
    </Card>
  );
}
