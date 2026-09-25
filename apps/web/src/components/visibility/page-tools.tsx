"use client";

import { DataSourceBadge } from "@/components/geo/data-source-badge";
import { ProjectSelect } from "@/components/shell/project-select";
import type { DataSource } from "@/lib/geo/types";
import { WINDOW_LABEL } from "@/lib/visibility/labels";
import type { VisibilityWindow } from "@ai-search-growth-os/types";
import { SegmentedControl } from "@ai-search-growth-os/ui";

/** Provenance badge + project picker + date range, shown in every AI Visibility header. */
export function VisibilityPageTools({
  source,
  reason,
  window,
  onWindowChange,
}: {
  source: DataSource;
  reason?: string | null;
  window: VisibilityWindow;
  onWindowChange: (w: VisibilityWindow) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DataSourceBadge source={source} reason={reason} />
      <ProjectSelect />
      <SegmentedControl
        aria-label="Date range"
        value={window}
        onValueChange={(w) => onWindowChange(w as VisibilityWindow)}
        options={(Object.keys(WINDOW_LABEL) as VisibilityWindow[]).map((w) => ({ value: w, label: WINDOW_LABEL[w] }))}
      />
    </div>
  );
}
