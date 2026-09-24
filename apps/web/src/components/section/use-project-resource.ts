"use client";

import * as React from "react";

import { useProject } from "@/components/project-provider";

interface FetchResult<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/**
 * Generic project-scoped loader used by the Competitive / Agents / Crawls
 * sections. Refetches when the selected project changes or `refresh()` is
 * called; optionally polls while `isActive(data)` returns true (used for
 * queued/running jobs, runs and workflows). Previous data stays visible while
 * a refresh is in flight.
 */
export function useProjectResource<T>(
  fetcher: (projectId: string) => Promise<T>,
  options: { pollMs?: number; isActive?: (data: T) => boolean } = {},
) {
  const { current, loading: projectLoading } = useProject();
  const projectId = current?.id ?? null;
  const [tick, setTick] = React.useState(0);
  const [result, setResult] = React.useState<FetchResult<T> | null>(null);
  const optionsRef = React.useRef(options);
  React.useEffect(() => {
    optionsRef.current = options;
  });

  const key = projectId ? `${projectId}:${tick}` : null;
  const refresh = React.useCallback(() => setTick((t) => t + 1), []);

  React.useEffect(() => {
    if (!key || !projectId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    fetcher(projectId)
      .then((data) => {
        if (cancelled) return;
        setResult({ key, data, error: null });
        const { pollMs, isActive } = optionsRef.current;
        if (pollMs && isActive?.(data)) timer = setTimeout(() => setTick((t) => t + 1), pollMs);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setResult({ key, data: null, error: err instanceof Error ? err.message : "Request failed" });
      });
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [key, projectId, fetcher]);

  const settled = key !== null && result?.key === key;
  return {
    projectId,
    project: current,
    projectLoading,
    data: projectId ? (result?.data ?? null) : null,
    loading: projectLoading || (projectId !== null && !settled && result?.data == null),
    refreshing: projectId !== null && !settled,
    error: projectId && settled ? (result?.error ?? null) : null,
    refresh,
  };
}
