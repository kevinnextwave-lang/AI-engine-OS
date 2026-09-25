import * as React from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "./utils";

/**
 * The one empty state, in three tones:
 * - `invitation` (default): the feature was never used — explain it and lead
 *   with a primary CTA. Never make "no data yet" look like an error.
 * - `neutral`: a filter or search matched nothing.
 * - `error`: the load failed — pair with a Retry action.
 *
 * API-compatible with the original `components/geo/empty-state.tsx`, which now
 * re-exports this component.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  tone = "invitation",
  children,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  tone?: "invitation" | "neutral" | "error";
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="empty-state"
      role={tone === "error" ? "alert" : undefined}
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-14 text-center",
        tone === "error" && "border-destructive/30 bg-destructive/5",
        className,
      )}
    >
      <Icon
        className={cn(
          "mb-3 size-8",
          tone === "error" ? "text-destructive" : "text-muted-foreground",
        )}
        aria-hidden="true"
      />
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground mt-1 max-w-md text-sm">{description}</p>
      {children && <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{children}</div>}
    </div>
  );
}
