"use client";

import { NetworkIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { MockNotice, DataSourceBadge } from "@/components/geo/data-source-badge";
import { EmptyState } from "@/components/geo/empty-state";
import { useProject } from "@/components/project-provider";
import { PageHeader } from "@/components/shell/page-header";
import { ErrorState } from "@/components/visibility/states";
import type { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import type { IntelligenceWindow } from "@/lib/intelligence/use-intelligence-data";
import { Button, NativeSelect } from "@ai-search-growth-os/ui";

type Intel = ReturnType<typeof useProjectIntelligence>;
const WINDOWS: { key: IntelligenceWindow; label: string }[] = [
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "180d", label: "180 days" },
];

export function runDisabledReason(d: Intel): string | null {
  if (d.source !== "api") return "Select a project to run prompts.";
  if (!d.runnableSet) return "Create a prompt set with active prompts first.";
  if (d.configuredProviders.length === 0) return "No AI provider is configured on the server (OPENAI_API_KEY, ANTHROPIC_API_KEY or GOOGLE_AI_API_KEY).";
  return null;
}

export function IntelligenceTools({ intel }: { intel: Intel }) {
  const { projects, current, select, loading } = useProject();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DataSourceBadge source={intel.source} reason={intel.mockReason} />
      <NativeSelect aria-label="Project" className="w-44" value={current?.id ?? ""} disabled={loading || projects.length === 0} onChange={(e) => select(e.target.value)}>
        {projects.length === 0 && <option value="">No projects</option>}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </NativeSelect>
      <div role="group" aria-label="Date range" className="bg-muted inline-flex rounded-md p-0.5 text-sm">
        {WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            aria-pressed={intel.window === w.key}
            onClick={() => intel.setWindow(w.key)}
            className={intel.window === w.key ? "bg-background text-foreground rounded-[5px] px-3 py-1 font-medium shadow-sm" : "text-muted-foreground hover:text-foreground rounded-[5px] px-3 py-1"}
          >
            {w.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Shared frame: header, provenance, error / empty states. */
export function IntelligencePageFrame({ intel, title, description, children }: { intel: Intel; title: string; description: string; children: React.ReactNode }) {
  const loading = intel.loading || intel.projectLoading;
  const reason = runDisabledReason(intel);
  return (
    <>
      <PageHeader title={title} description={description}>
        <IntelligenceTools intel={intel} />
      </PageHeader>
      <MockNotice source={intel.source} reason={intel.mockReason} />
      {intel.error ? (
        <ErrorState message={intel.error} onRetry={intel.actions.refresh} />
      ) : !loading && intel.empty ? (
        <EmptyState
          icon={NetworkIcon}
          title="Run more AI searches to build your citation intelligence graph."
          description="Citation intelligence is built from the sources AI engines cite when answering your prompts. No citations were observed in this period yet."
        >
          <div className="flex flex-col items-center gap-2">
            <div className="flex gap-2">
              <Button onClick={() => void intel.actions.runPromptSet()} disabled={reason !== null || intel.busy === "run"} title={reason ?? undefined}>
                {intel.busy === "run" ? "Queuing…" : "Run AI Search Analysis"}
              </Button>
              <Button asChild variant="outline">
                <Link href="/app/ai-visibility/prompts">Prompts</Link>
              </Button>
            </div>
            {intel.runNotice && <p className="text-muted-foreground max-w-md text-xs">{intel.runNotice}</p>}
            {reason && <p className="text-muted-foreground max-w-md text-xs">{reason}</p>}
          </div>
        </EmptyState>
      ) : (
        children
      )}
    </>
  );
}
