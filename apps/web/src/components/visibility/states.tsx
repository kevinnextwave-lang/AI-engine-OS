"use client";

import { AlertTriangleIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/geo/empty-state";
import { Button } from "@ai-search-growth-os/ui";

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="border-destructive/40 bg-destructive/5 flex flex-col items-start gap-3 rounded-xl border p-5 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <AlertTriangleIcon className="text-destructive size-4" aria-hidden="true" />
        Could not load AI visibility data
      </p>
      <p className="text-muted-foreground">{message}</p>
      <Button size="sm" variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

/**
 * Shown when a selected project has no parsed AI responses in the window.
 * No numbers are displayed here — there is nothing measured to show.
 */
export function NoDataState({
  canRun,
  runDisabledReason,
  busy,
  onRun,
  notice,
}: {
  canRun: boolean;
  runDisabledReason: string | null;
  busy: boolean;
  onRun: () => void;
  notice: string | null;
}) {
  return (
    <EmptyState
      icon={SparklesIcon}
      title="Run your first AI Search analysis"
      description="AI visibility is measured from real answers AI engines give to your prompts. Run a prompt set to collect responses; scores appear once at least 5 responses have been parsed."
    >
      <div className="flex flex-col items-center gap-2">
        <div className="flex gap-2">
          <Button onClick={onRun} disabled={!canRun || busy} title={runDisabledReason ?? undefined}>
            {busy ? "Queuing…" : "Run Prompt Set"}
          </Button>
          <Button asChild variant="outline">
            <Link href="/app/projects">Project settings</Link>
          </Button>
        </div>
        {notice && <p className="text-muted-foreground max-w-md text-xs">{notice}</p>}
        {!canRun && runDisabledReason && <p className="text-muted-foreground max-w-md text-xs">{runDisabledReason}</p>}
      </div>
    </EmptyState>
  );
}

export function runDisabledReason(d: {
  source: "api" | "mock";
  runnableSet: { name: string } | null;
  configuredProviders: string[];
}): string | null {
  if (d.source !== "api") return "Select a project to run prompts.";
  if (!d.runnableSet) return "Create a prompt set with active prompts first.";
  if (d.configuredProviders.length === 0) return "No AI provider is configured on the server (OPENAI_API_KEY, ANTHROPIC_API_KEY or GOOGLE_AI_API_KEY).";
  return null;
}
