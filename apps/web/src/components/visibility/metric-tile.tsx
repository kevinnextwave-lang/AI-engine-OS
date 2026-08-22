import { ArrowDownRightIcon, ArrowUpRightIcon, MinusIcon } from "lucide-react";

import { fmtChange, fmtValue } from "@/components/visibility/format";
import type { VisibilityMetric } from "@/lib/visibility/types";
import { Card, CardContent, Skeleton, cn } from "@ai-search-growth-os/ui";

function ChangeLine({ metric }: { metric: VisibilityMetric }) {
  if (metric.change == null) {
    return (
      <p className="text-muted-foreground text-xs" title={metric.unavailableReason ?? undefined}>
        {metric.value == null ? (metric.unavailableReason ?? "Not enough data") : "No comparison available"}
      </p>
    );
  }
  const better = metric.lowerIsBetter ? metric.change < 0 : metric.change > 0;
  const flat = Math.abs(metric.change) < (metric.unit === "position" ? 0.1 : 2);
  const Icon = flat ? MinusIcon : better ? ArrowUpRightIcon : ArrowDownRightIcon;
  return (
    <p
      className={cn(
        "flex items-center gap-1 text-xs tabular-nums",
        flat ? "text-muted-foreground" : better ? "text-emerald-700 dark:text-emerald-400" : "text-orange-700 dark:text-orange-400",
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {fmtChange(metric.change, metric.unit)} vs previous period
    </p>
  );
}

export function MetricTile({ metric, emphasis = false }: { metric: VisibilityMetric; emphasis?: boolean }) {
  return (
    <Card className={cn("gap-2 py-4", emphasis && "border-primary/40")}>
      <CardContent className="flex flex-col gap-2 px-4">
        <p className="text-muted-foreground text-sm font-medium" title={metric.note}>
          {metric.label}
        </p>
        <p className={cn("font-semibold tabular-nums", emphasis ? "text-4xl" : "text-3xl")}>
          {metric.value == null ? <span className="text-muted-foreground">–</span> : fmtValue(metric.value, metric.unit)}
          {metric.value != null && metric.unit === "score" && (
            <span className="text-muted-foreground ml-1 text-base font-normal">/100</span>
          )}
        </p>
        <ChangeLine metric={metric} />
        <p className="text-muted-foreground text-xs">
          n = {metric.sampleSize} response{metric.sampleSize === 1 ? "" : "s"}
        </p>
      </CardContent>
    </Card>
  );
}

export function MetricTileSkeleton() {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex flex-col gap-2 px-4">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-9 w-20" />
        <Skeleton className="h-3 w-36" />
        <Skeleton className="h-3 w-24" />
      </CardContent>
    </Card>
  );
}
