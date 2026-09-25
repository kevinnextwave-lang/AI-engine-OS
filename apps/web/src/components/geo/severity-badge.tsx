import { SEVERITY_LABEL, STATUS_LABEL } from "@/lib/geo/labels";
import type { ObservationStatus, Severity } from "@ai-search-growth-os/types";
import { Badge, cn } from "@ai-search-growth-os/ui";

/** Soft-tinted severity chip; fixed width so table columns align. */
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <Badge variant={severity} className={cn("w-16 justify-center", className)}>
      {SEVERITY_LABEL[severity]}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: ObservationStatus }) {
  const variant = status === "resolved" ? "success" : status === "ignored" ? "muted" : "outline";
  return <Badge variant={variant}>{STATUS_LABEL[status]}</Badge>;
}
