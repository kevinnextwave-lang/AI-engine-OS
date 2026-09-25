"use client";

import { SparklesIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/geo/empty-state";
import { LoadError } from "@/components/shell/load-error";
import { Button } from "@ai-search-growth-os/ui";

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <LoadError what="AI visibility data" message={message} onRetry={onRetry} />;
}

/**
 * Shown when a selected project has no parsed AI responses in the window.
 * No numbers are displayed here — there is nothing measured to show.
 */
export function NoDataState({
  canRun,
  runDisabledReason,
  busy,
  generating,
  needsPrompts,
  onRun,
  onGenerate,
  notice,
}: {
  canRun: boolean;
  runDisabledReason: string | null;
  busy: boolean;
  generating: boolean;
  /** No prompt set with active prompts exists yet — offer generation first. */
  needsPrompts: boolean;
  onRun: () => void;
  onGenerate: () => void;
  notice: string | null;
}) {
  return (
    <EmptyState
      icon={SparklesIcon}
      title={needsPrompts ? "Create your prompts first" : "Run your first AI Search analysis"}
      description={
        needsPrompts
          ? "Prompts are the real buyer questions the AI engines get asked (\u201cbest X for Y\u201d). Generate a starter set from your project's brand, website and competitors — you can edit it afterwards."
          : "AI visibility is measured from real answers AI engines give to your prompts. Run a prompt set to collect responses; scores appear once at least 5 responses have been parsed."
      }
    >
      <div className="flex flex-col items-center gap-2">
        <div className="flex gap-2">
          {needsPrompts ? (
            <Button onClick={onGenerate} disabled={generating}>
              {generating ? "Generating…" : "Generate prompts"}
            </Button>
          ) : (
            <Button onClick={onRun} disabled={!canRun || busy} title={runDisabledReason ?? undefined}>
              {busy ? "Queuing…" : "Run Prompt Set"}
            </Button>
          )}
          <Button asChild variant="outline">
            <Link href="/app/projects">Project settings</Link>
          </Button>
        </div>
        {notice && <p className="text-muted-foreground max-w-md text-xs">{notice}</p>}
        {!needsPrompts && !canRun && runDisabledReason && (
          <p className="text-muted-foreground max-w-md text-xs">{runDisabledReason}</p>
        )}
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
