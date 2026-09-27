"use client";

import * as React from "react";

import { useProject } from "@/components/project-provider";
import { label } from "@/components/section/primitives";
import { api } from "@/lib/api";
import type { ChartEvent } from "@/lib/verify";

/**
 * Real, timestamped action events for chart markers: completed agent runs
 * and (optionally) created content briefs. One fetch per project per mount,
 * no polling; failures degrade to "no markers", never to an error state —
 * the chart itself is unaffected.
 */
export function useActionEvents({ briefs = false }: { briefs?: boolean } = {}): ChartEvent[] {
  const { current } = useProject();
  const projectId = current?.id ?? null;
  const [state, setState] = React.useState<{ projectId: string; events: ChartEvent[] } | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    Promise.all([
      api.agents.runs(projectId, { limit: 20 }),
      briefs ? api.contentBriefs.list(projectId, { limit: 20 }) : Promise.resolve(null),
    ])
      .then(([runs, briefList]) => {
        if (cancelled) return;
        const events: ChartEvent[] = [];
        for (const r of runs.items) {
          if ((r.status === "completed" || r.status === "awaiting_approval") && r.completed_at) {
            events.push({
              ts: Date.parse(r.completed_at),
              label: `${label(r.agent_name)} run`,
              detail: r.objective,
            });
          }
        }
        for (const b of briefList?.items ?? []) {
          events.push({
            ts: Date.parse(b.created_at),
            label: "Content brief created",
            detail: b.title,
          });
        }
        setState({ projectId, events });
      })
      .catch(() => !cancelled && setState({ projectId, events: [] }));
    return () => {
      cancelled = true;
    };
  }, [projectId, briefs]);

  return state?.projectId === projectId ? state.events : [];
}
