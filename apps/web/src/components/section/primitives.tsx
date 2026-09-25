"use client";

import * as React from "react";

import { Badge, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "info"
  | "success"
  | "muted";

const STATUS_VARIANTS: Record<string, BadgeVariant> = {
  // generic lifecycle
  queued: "info",
  running: "medium",
  completed: "success",
  partially_completed: "medium",
  failed: "critical",
  cancelled: "muted",
  paused: "info",
  awaiting_approval: "high",
  // review / decision states
  new: "info",
  reviewing: "medium",
  accepted: "success",
  approved: "success",
  rejected: "muted",
  dismissed: "muted",
  read: "muted",
  draft: "outline",
  in_progress: "medium",
  archived: "muted",
  pending: "high",
  edited: "success",
  executed: "success",
  // crawl URL lifecycle
  discovered: "info",
  crawling: "medium",
  crawled: "success",
  skipped: "muted",
  cancelling: "medium",
  // severity / confidence
  critical: "critical",
  high: "high",
  medium: "medium",
  moderate: "medium",
  low: "low",
  insufficient: "muted",
};

export function statusVariant(value: string): BadgeVariant {
  return STATUS_VARIANTS[value] ?? "secondary";
}

export function label(value: string): string {
  const text = value.replaceAll("_", " ");
  // One label convention app-wide: Sentence case ("Awaiting approval").
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function StatusBadge({ value, className }: { value: string; className?: string }) {
  return (
    <Badge variant={statusVariant(value)} className={className}>
      {label(value)}
    </Badge>
  );
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-2">
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} className="h-8 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * Rich table empty state: the same four-part anatomy as EmptyState (state,
 * what the section does + why it's empty + what to do next, primary CTA),
 * rendered compactly inside the table so the layout stays stable.
 */
export interface TableEmptyState {
  title: string;
  /** What this section does, why it's empty, and what to do next. */
  description: string;
  /** Primary CTA (a Button or Link). */
  action?: React.ReactNode;
}

/** Table with loading and empty handling; header cells from `head`. */
export function DataTable({
  head,
  loading,
  empty,
  children,
}: {
  head: string[];
  loading: boolean;
  /** A TableEmptyState (preferred) or a plain one-line message. */
  empty: TableEmptyState | string | null;
  children: React.ReactNode;
}) {
  if (loading) return <TableSkeleton cols={head.length} />;
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            {head.map((h, i) => (
              <TableHead key={h || `col-${i}`}>
                {/* An empty string marks an actions column; give it an sr-only name. */}
                {h || <span className="sr-only">Actions</span>}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {empty ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={head.length} className="py-12">
                {typeof empty === "string" ? (
                  <p className="text-muted-foreground text-center text-sm">{empty}</p>
                ) : (
                  <div className="mx-auto flex max-w-md flex-col items-center gap-1 text-center">
                    <p className="text-sm font-medium">{empty.title}</p>
                    <p className="text-muted-foreground text-sm">{empty.description}</p>
                    {empty.action && <div className="mt-3">{empty.action}</div>}
                  </div>
                )}
              </TableCell>
            </TableRow>
          ) : (
            children
          )}
        </TableBody>
      </Table>
    </div>
  );
}
