"use client";

import { DataSourceBadge } from "@/components/geo/data-source-badge";
import { ProjectSelect } from "@/components/shell/project-select";
import type { DataSource } from "@/lib/geo/types";

/** Project picker + provenance badge shown in every GEO page header. */
export function GeoPageTools({ source, reason }: { source: DataSource; reason?: string | null }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DataSourceBadge source={source} reason={reason} />
      <ProjectSelect />
    </div>
  );
}
