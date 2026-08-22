"use client";

import * as React from "react";

import { useOrganization } from "@/components/organization-provider";
import { api } from "@/lib/api";
import type { Project } from "@ai-search-growth-os/types";

interface ProjectContextValue {
  projects: Project[];
  current: Project | null;
  loading: boolean;
  error: string | null;
  select: (id: string) => void;
}

interface Loaded {
  organizationId: string;
  projects: Project[];
  error: string | null;
}

const ProjectContext = React.createContext<ProjectContextValue | undefined>(undefined);
const STORAGE_KEY = "asg:current-project";

function readStoredId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Projects of the selected organization and the one the GEO section works on. */
export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const { current: organization } = useOrganization();
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!organization) return;
    let cancelled = false;
    api.projects
      .list(organization.id)
      .then((res) => {
        if (!cancelled) setLoaded({ organizationId: organization.id, projects: res.items, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoaded({
            organizationId: organization.id,
            projects: [],
            error: err instanceof Error ? err.message : "Could not load projects",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [organization]);

  const select = React.useCallback((id: string) => {
    setSelectedId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* selection still works for this session */
    }
  }, []);

  const value = React.useMemo<ProjectContextValue>(() => {
    const ready = organization !== null && loaded?.organizationId === organization.id;
    const projects = ready ? loaded.projects : [];
    const candidate = selectedId ?? readStoredId();
    const current =
      projects.find((p) => p.id === candidate) ?? projects[0] ?? null;
    return {
      projects,
      current,
      loading: organization !== null && !ready,
      error: ready ? loaded.error : null,
      select,
    };
  }, [organization, loaded, selectedId, select]);
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject(): ProjectContextValue {
  const ctx = React.useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used inside ProjectProvider");
  return ctx;
}
