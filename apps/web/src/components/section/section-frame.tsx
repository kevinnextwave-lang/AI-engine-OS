"use client";

import { FolderKanbanIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { AppPageFrame } from "@/components/shell/app-page-frame";
import { Button } from "@ai-search-growth-os/ui";

/**
 * Frame for the Competitive / Agents / Crawls sections: shared chrome via
 * AppPageFrame, plus this domain's specific gate — these pages need a
 * selected project before they can show anything.
 */
export function SectionFrame({
  title,
  description,
  tools,
  projectId,
  projectLoading,
  error,
  onRetry,
  children,
}: {
  title: string;
  description: string;
  tools?: React.ReactNode;
  projectId: string | null;
  projectLoading: boolean;
  error: string | null;
  onRetry: () => void;
  children: React.ReactNode;
}) {
  const needsProject = !projectLoading && !projectId;
  return (
    <AppPageFrame
      title={title}
      description={description}
      tools={tools}
      // The project gate outranks the error branch: without a project there
      // is nothing to retry.
      error={needsProject ? null : error}
      onRetry={onRetry}
      gate={
        needsProject ? (
          <EmptyState
            icon={FolderKanbanIcon}
            title="Select a project"
            description="This page works on one project's data. Create or select a project first."
          >
            <Button asChild variant="outline">
              <Link href="/app/projects">Go to projects</Link>
            </Button>
          </EmptyState>
        ) : null
      }
    >
      {children}
    </AppPageFrame>
  );
}

/** One-line meta text + an action button aligned right above a table. */
export function Toolbar({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>;
}
