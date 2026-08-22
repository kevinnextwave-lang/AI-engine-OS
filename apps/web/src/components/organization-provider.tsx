"use client";

import * as React from "react";

import { api, type Organization } from "@/lib/api";

interface OrganizationContextValue {
  organizations: Organization[];
  current: Organization | null;
  loading: boolean;
  error: string | null;
  select: (id: string) => void;
  refresh: () => void;
}

const OrganizationContext = React.createContext<OrganizationContextValue | undefined>(undefined);

const STORAGE_KEY = "asg:current-organization";

function readStoredId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* storage unavailable — selection still works for this session */
  }
}

/**
 * Holds the caller's organizations and the currently selected one.
 * Mounted only inside the authenticated /app layout, so a user always exists.
 */
export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const [organizations, setOrganizations] = React.useState<Organization[]>([]);
  const [currentId, setCurrentId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [version, setVersion] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    api.organizations
      .list()
      .then((orgs) => {
        if (cancelled) return;
        setOrganizations(orgs);
        setCurrentId((prev) => {
          const candidate = prev ?? readStoredId();
          if (candidate && orgs.some((o) => o.id === candidate)) return candidate;
          return orgs[0]?.id ?? null;
        });
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your organizations.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  const select = React.useCallback((id: string) => {
    setCurrentId(id);
    writeStoredId(id);
  }, []);

  const refresh = React.useCallback(() => setVersion((v) => v + 1), []);

  const value = React.useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      current: organizations.find((o) => o.id === currentId) ?? null,
      loading,
      error,
      select,
      refresh,
    }),
    [organizations, currentId, loading, error, select, refresh],
  );

  return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}

export function useOrganization(): OrganizationContextValue {
  const ctx = React.useContext(OrganizationContext);
  if (!ctx) throw new Error("useOrganization must be used within <OrganizationProvider>");
  return ctx;
}
