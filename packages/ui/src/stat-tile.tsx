import * as React from "react";
import { MinusIcon, TrendingDownIcon, TrendingUpIcon } from "lucide-react";

import { Skeleton } from "./skeleton";
import { cn } from "./utils";

/**
 * THE metric tile. Replaces the seven per-section KPI implementations so every
 * dashboard number shares one anatomy: label, value(+unit), delta, context.
 *
 * - `size="hero"` is for a page's single headline number; `default` for the
 *   supporting row.
 * - `delta` is colored by direction via the semantic tokens; pass
 *   `positiveIsGood={false}` for metrics where up is bad.
 */
function StatTile({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  positiveIsGood = true,
  context,
  size = "default",
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  unit?: React.ReactNode;
  /** Numeric change vs the previous period; 0 or undefined renders as stable. */
  delta?: number | null;
  /** Overrides the default "vs previous period" wording. */
  deltaLabel?: React.ReactNode;
  positiveIsGood?: boolean;
  /** Sample-size / methodology line, e.g. "84 responses". */
  context?: React.ReactNode;
  size?: "default" | "hero";
  className?: string;
}) {
  const direction = delta == null || delta === 0 ? "flat" : delta > 0 ? "up" : "down";
  const good = direction === "flat" ? null : (direction === "up") === positiveIsGood;
  const DeltaIcon =
    direction === "up" ? TrendingUpIcon : direction === "down" ? TrendingDownIcon : MinusIcon;

  return (
    <div
      data-slot="stat-tile"
      className={cn("bg-card shadow-card flex flex-col gap-1 rounded-xl border p-4", className)}
    >
      <p className="text-muted-foreground text-xs font-medium tracking-wide">{label}</p>
      <p
        data-slot="stat-tile-value"
        className={cn(
          "font-semibold tracking-tight",
          size === "hero" ? "text-3xl" : "text-2xl",
        )}
      >
        {value}
        {unit != null && <span className="text-muted-foreground ml-0.5 text-sm font-normal">{unit}</span>}
      </p>
      {(delta != null || deltaLabel != null) && (
        <p
          className={cn(
            "flex items-center gap-1 text-xs",
            good == null ? "text-muted-foreground" : good ? "text-success" : "text-destructive",
          )}
        >
          <DeltaIcon className="size-3.5" aria-hidden="true" />
          {deltaLabel ??
            (direction === "flat"
              ? "no change vs previous period"
              : `${delta! > 0 ? "+" : ""}${delta} vs previous period`)}
        </p>
      )}
      {context && <p className="text-muted-foreground text-xs">{context}</p>}
    </div>
  );
}

function StatTileSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("bg-card shadow-card flex flex-col gap-2 rounded-xl border p-4", className)}>
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="h-8 w-16" />
      <Skeleton className="h-3.5 w-32" />
    </div>
  );
}

export { StatTile, StatTileSkeleton };
