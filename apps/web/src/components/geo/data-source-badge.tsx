import { DatabaseIcon, FlaskConicalIcon } from "lucide-react";

import type { DataSource } from "@/lib/geo/types";
import { Badge } from "@ai-search-growth-os/ui";

/** Always visible next to GEO data so API data and sample data are never confused. */
export function DataSourceBadge({ source, reason }: { source: DataSource; reason?: string | null }) {
  if (source === "api") {
    return (
      <Badge variant="outline" title="Loaded from the API for the selected project">
        <DatabaseIcon className="size-3" aria-hidden="true" />
        Live API data
      </Badge>
    );
  }
  return (
    <Badge variant="medium" title={reason ?? "Sample data"}>
      <FlaskConicalIcon className="size-3" aria-hidden="true" />
      Mock data
    </Badge>
  );
}

export function MockNotice({ source, reason }: { source: DataSource; reason: string | null }) {
  if (source !== "mock") return null;
  return (
    <div
      role="status"
      className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm"
    >
      <strong className="font-medium">Sample data.</strong> {reason ?? "Not connected to the API."}{" "}
      Nothing shown here comes from your website.
    </div>
  );
}
