"use client";

import { useProject } from "@/components/project-provider";
import { useIntelligenceData, type IntelligenceData } from "@/lib/intelligence/use-intelligence-data";

export function useProjectIntelligence(): IntelligenceData & { projectLoading: boolean } {
  const { current, loading } = useProject();
  const data = useIntelligenceData(loading ? null : (current?.id ?? null), current?.name ?? null);
  return { ...data, projectLoading: loading };
}
