"use client";

import { useProject } from "@/components/project-provider";
import { NativeSelect } from "@ai-search-growth-os/ui";
import { cn } from "@ai-search-growth-os/ui";

/** THE project picker used in page-header toolbars. One width everywhere. */
export function ProjectSelect({ className }: { className?: string }) {
  const { projects, current, select, loading } = useProject();
  return (
    <NativeSelect
      aria-label="Project"
      className={cn("w-44", className)}
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
  );
}
