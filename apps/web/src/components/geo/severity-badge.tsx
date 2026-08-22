import { SEVERITY_LABEL, STATUS_LABEL } from "@/lib/geo/labels";
import type { ObservationStatus, Severity } from "@ai-search-growth-os/types";
import { Badge } from "@ai-search-growth-os/ui";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge variant={severity}>{SEVERITY_LABEL[severity].toUpperCase()}</Badge>;
}

export function StatusBadge({ status }: { status: ObservationStatus }) {
  const variant = status === "resolved" ? "success" : status === "ignored" ? "muted" : "outline";
  return <Badge variant={variant}>{STATUS_LABEL[status]}</Badge>;
}
