"use client";

import { useProject } from "@/components/project-provider";
import { DataSourceBadge } from "@/components/geo/data-source-badge";
import type { DataSource } from "@/lib/geo/types";
import { NativeSelect } from "@ai-search-growth-os/ui";

/** Project picker + provenance badge shown in every GEO page header. */
export function GeoPageTools({ source, reason }: { source: DataSource; reason?: string | null }) {
  const { projects, current, select, loading } = useProject();
  return (
    <div className="flex items-center gap-2">
      <DataSourceBadge source={source} reason={reason} />
      <NativeSelect
        aria-label="Project"
        className="w-48"
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
    </div>
  );
}
