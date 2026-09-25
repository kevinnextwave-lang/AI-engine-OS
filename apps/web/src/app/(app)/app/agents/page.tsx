"use client";

import * as React from "react";

import { StatusBadge } from "@/components/section/primitives";
import { SectionFrame } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { AgentRunListResponse } from "@ai-search-growth-os/types";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from "@ai-search-growth-os/ui";
import Link from "next/link";

const AGENT_INFO: Record<string, { title: string; description: string }> = {
  research: {
    title: "Research Agent",
    description:
      "Analyzes your measured data — competitive advantages, citation and content gaps, entity signals, technical SEO, repeated competitor claims — and produces prioritized findings with evidence. Deterministic: it only reports what was measured.",
  },
  "content-strategy": {
    title: "Content Strategy Agent",
    description:
      "Turns high-scoring content gaps into structured content briefs: objective, audience, outline, information and evidence requirements. It never writes the content itself and never invents statistics.",
  },
  "content-optimization": {
    title: "Content Optimization Agent",
    description:
      "Reviews crawled pages for answerability, specificity, evidence and structure, proposing text changes you accept, edit or reject. The original page is never modified automatically.",
  },
  "entity-optimization": {
    title: "Entity Optimization Agent",
    description:
      "Checks organization, product, service and people entities plus cross-page consistency, proposing structured-data improvements. All modifications require your approval.",
  },
};

export default function AgentsPage() {
  const agents = useProjectResource<{ name: string; version: string }[]>(
    React.useCallback((pid) => api.agents.list(pid), []),
  );
  const runs = useProjectResource<AgentRunListResponse>(
    React.useCallback((pid) => api.agents.runs(pid, { limit: 8 }), []),
    { pollMs: 4000, isActive: (d) => d.items.some((r) => r.status === "queued" || r.status === "running") },
  );
  const [objective, setObjective] = React.useState("");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const run = async (name: string) => {
    if (!agents.projectId) return;
    setBusy(name);
    setNotice(null);
    try {
      await api.agents.run(
        agents.projectId,
        name,
        objective.trim() || `Run the ${AGENT_INFO[name]?.title ?? name} on this project`,
      );
      setNotice(`${AGENT_INFO[name]?.title ?? name} queued. Track it under Runs & Approvals.`);
      runs.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not queue the agent");
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionFrame
      title="Agents"
      description="Autonomous analysis agents that work only on this project's measured data through a controlled tool registry. Agents propose; you approve — no proposed action is ever executed automatically."
      projectId={agents.projectId}
      projectLoading={agents.projectLoading}
      error={agents.error ?? runs.error}
      onRetry={() => {
        agents.refresh();
        runs.refresh();
      }}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          aria-label="Objective"
          placeholder="Optional objective, e.g. “Grow AI visibility for comparison prompts”"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          className="max-w-xl flex-1"
        />
      </div>
      {notice && <p className="text-muted-foreground mb-4 text-sm">{notice}</p>}
      {agents.loading && (
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="bg-muted/40 h-40 animate-pulse rounded-xl border" />
          ))}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(agents.data ?? []).map((a) => {
          const info = AGENT_INFO[a.name] ?? { title: a.name, description: "" };
          return (
            <Card key={a.name}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between text-base">
                  {info.title}
                  <span className="text-muted-foreground text-xs font-normal">v{a.version}</span>
                </CardTitle>
                <CardDescription>{info.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button size="sm" onClick={() => void run(a.name)} disabled={busy !== null}>
                  {busy === a.name ? "Queuing…" : "Run agent"}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
      {runs.data && runs.data.items.length > 0 && (
        <div className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recent runs</h2>
            <Button asChild size="sm" variant="outline">
              <Link href="/app/agents/runs">All runs & approvals</Link>
            </Button>
          </div>
          <ul className="flex flex-col gap-2">
            {runs.data.items.map((r) => (
              <li key={r.id} className="flex items-center justify-between rounded-lg border px-4 py-2.5 text-sm">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="font-medium">{AGENT_INFO[r.agent_name]?.title ?? r.agent_name}</span>
                  <span className="text-muted-foreground truncate">{r.objective}</span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="text-muted-foreground text-xs">{fmtDateTime(r.created_at)}</span>
                  <StatusBadge value={r.status} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SectionFrame>
  );
}
