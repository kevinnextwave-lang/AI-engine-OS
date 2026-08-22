"use client";

import { useProject } from "@/components/project-provider";
import { useVisibilityData, type VisibilityData } from "@/lib/visibility/use-visibility-data";

/** AI Visibility data for the selected project (or sample data when none). */
export function useProjectVisibility(): VisibilityData & { projectLoading: boolean } {
  const { current, loading } = useProject();
  const data = useVisibilityData(loading ? null : (current?.id ?? null), current?.name ?? null);
  return { ...data, projectLoading: loading };
}
