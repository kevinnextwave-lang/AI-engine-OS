"use client";

import { DataSourceBadge } from "@/components/geo/data-source-badge";
import { useProject } from "@/components/project-provider";
import type { DataSource } from "@/lib/geo/types";
import { WINDOW_LABEL } from "@/lib/visibility/labels";
import type { VisibilityWindow } from "@ai-search-growth-os/types";
import { NativeSelect } from "@ai-search-growth-os/ui";

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
  const { projects, current, select, loading } = useProject();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DataSourceBadge source={source} reason={reason} />
      <NativeSelect
        aria-label="Project"
        className="w-44"
        value={current?.id ?? ""}
        disabled={loading || projects.length === 0}
        onChange={(e) => select(e.target.value)}
      >
        {projects.length === 0 && <option value="">No projects</option>}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </NativeSelect>
      <div role="group" aria-label="Date range" className="bg-muted inline-flex rounded-md p-0.5 text-sm">
        {(Object.keys(WINDOW_LABEL) as VisibilityWindow[]).map((w) => (
          <button
            key={w}
            type="button"
            aria-pressed={window === w}
            onClick={() => onWindowChange(w)}
            className={
              window === w
                ? "bg-background text-foreground rounded-[5px] px-3 py-1 font-medium shadow-sm"
                : "text-muted-foreground hover:text-foreground rounded-[5px] px-3 py-1"
            }
          >
            {WINDOW_LABEL[w]}
          </button>
        ))}
      </div>
    </div>
  );
}
