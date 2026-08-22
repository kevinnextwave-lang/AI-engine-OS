"use client";

import { useProject } from "@/components/project-provider";
import { useGeoData, type GeoData } from "@/lib/geo/use-geo-data";

/** GEO data for the currently selected project (or sample data when none). */
export function useProjectGeo(): GeoData & { projectLoading: boolean } {
  const { current, loading } = useProject();
  const data = useGeoData(loading ? null : (current?.id ?? null));
  return { ...data, projectLoading: loading };
}
