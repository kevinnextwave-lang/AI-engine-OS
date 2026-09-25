"use client";

import { FolderKanbanIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { LoadError } from "@/components/shell/load-error";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@ai-search-growth-os/ui";

/**
 * Shared frame for the Competitive / Agents / Crawls sections: header with
 * tools, a "select a project" state, and the error state. Children render only
 * when a project is selected and the load did not fail.
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
  return (
    <>
      <PageHeader title={title} description={description}>
        {tools}
      </PageHeader>
      {!projectLoading && !projectId ? (
        <EmptyState
          icon={FolderKanbanIcon}
          title="Select a project"
          description="This page works on one project's data. Create or select a project first."
        >
          <Button asChild variant="outline">
            <Link href="/app/projects">Go to projects</Link>
          </Button>
        </EmptyState>
      ) : error ? (
        <LoadError what={title.toLowerCase()} message={error} onRetry={onRetry} />
      ) : (
        children
      )}
    </>
  );
}

/** One-line meta text + an action button aligned right above a table. */
export function Toolbar({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>;
}
