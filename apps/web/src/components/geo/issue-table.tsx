"use client";

import { ArrowDownIcon, ArrowUpIcon, ArrowUpDownIcon, SearchXIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { SeverityBadge, StatusBadge } from "@/components/geo/severity-badge";
import { displayPath } from "@/lib/geo/overview";
import type { GeoIssue, SortDirection, SortKey } from "@/lib/geo/types";
import {
  Button,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  cn,
} from "@ai-search-growth-os/ui";

/**
 * The issues table. Scannable hierarchy per row:
 * SEVERITY · ISSUE (title + quiet category/path context) · AFFECTED PAGES ·
 * STATUS · ACTION. Full URLs and evidence live in the drawer, not here.
 */

const COLUMNS: Array<{ key: SortKey | "action" | "select"; label: string; sortable: boolean; className?: string }> = [
  { key: "select", label: "", sortable: false, className: "w-10" },
  { key: "severity", label: "Severity", sortable: true, className: "w-24" },
  { key: "title", label: "Issue", sortable: true },
  { key: "affected", label: "Affected pages", sortable: true, className: "hidden w-32 text-right md:table-cell" },
  { key: "status", label: "Status", sortable: true, className: "hidden w-24 sm:table-cell" },
  { key: "action", label: "", sortable: false, className: "w-20" },
];

export function IssueTable({
  issues,
  loading,
  sortKey,
  sortDir,
  onSort,
  onOpen,
  selectable = false,
  selected,
  onToggle,
  onToggleAll,
  emptyTitle = "No issues match",
  emptyDescription = "Adjust the filters, or run a GEO audit to generate observations.",
}: {
  issues: GeoIssue[];
  loading?: boolean;
  sortKey: SortKey;
  sortDir: SortDirection;
  onSort: (key: SortKey) => void;
  onOpen: (issue: GeoIssue) => void;
  /** Show checkboxes for issues that support status updates (bulk triage). */
  selectable?: boolean;
  selected?: ReadonlySet<string>;
  onToggle?: (issue: GeoIssue) => void;
  onToggleAll?: (issues: GeoIssue[]) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (!loading && issues.length === 0) {
    return <EmptyState icon={SearchXIcon} title={emptyTitle} description={emptyDescription} tone="neutral" />;
  }
  const columns = selectable ? COLUMNS : COLUMNS.filter((c) => c.key !== "select");
  const triageable = issues.filter((i) => i.canUpdateStatus);
  const allSelected = triageable.length > 0 && triageable.every((i) => selected?.has(i.id));
  return (
    <div className="overflow-hidden rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((col) => {
              const active = col.sortable && sortKey === col.key;
              return (
                <TableHead
                  key={col.key}
                  className={col.className}
                  aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
                >
                  {col.key === "select" ? (
                    <input
                      type="checkbox"
                      aria-label="Select all issues that can be triaged"
                      className="accent-primary size-3.5 align-middle"
                      checked={allSelected}
                      disabled={triageable.length === 0}
                      onChange={() => onToggleAll?.(triageable)}
                    />
                  ) : col.sortable ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.key as SortKey)}
                      className={cn("hover:text-foreground inline-flex items-center gap-1 uppercase", active && "text-foreground")}
                    >
                      {col.label}
                      {active ? (
                        sortDir === "asc" ? <ArrowUpIcon className="size-3" /> : <ArrowDownIcon className="size-3" />
                      ) : (
                        <ArrowUpDownIcon className="size-3 opacity-50" />
                      )}
                    </button>
                  ) : col.key === "action" ? (
                    // Header must not be empty for screen readers.
                    <span className="sr-only">Actions</span>
                  ) : (
                    col.label
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading
            ? Array.from({ length: 6 }, (_, i) => (
                <TableRow key={i}>
                  {columns.map((col) => (
                    <TableCell key={col.key} className={cn(col.className, "py-3")}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : issues.map((issue) => (
                <TableRow
                  key={issue.id}
                  className="hover:bg-muted/50 group cursor-pointer border-b last:border-b-0"
                  onClick={() => onOpen(issue)}
                >
                  {selectable && (
                    <TableCell className="py-3" onClick={(e) => e.stopPropagation()}>
                      {issue.canUpdateStatus && (
                        <input
                          type="checkbox"
                          aria-label={`Select ${issue.title}`}
                          className="accent-primary size-3.5 align-middle"
                          checked={selected?.has(issue.id) ?? false}
                          onChange={() => onToggle?.(issue)}
                        />
                      )}
                    </TableCell>
                  )}
                  <TableCell className="py-3 align-top">
                    <SeverityBadge severity={issue.severity} />
                  </TableCell>
                  <TableCell className="min-w-0 py-3">
                    <p className="truncate text-sm font-medium" title={issue.title}>
                      {issue.title}
                    </p>
                    {/* Quiet context: category, plus the page path for page-level
                        issues. The full URL lives in the drawer. */}
                    <p className="text-muted-foreground mt-0.5 truncate text-xs" title={issue.url ?? undefined}>
                      {issue.category}
                      {issue.url && <> · {displayPath(issue.url)}</>}
                    </p>
                  </TableCell>
                  <TableCell className="hidden py-3 text-right text-sm tabular-nums md:table-cell">
                    {issue.affectedCount === 0
                      ? "Site-wide"
                      : `${issue.affectedCount} ${issue.affectedCount === 1 ? "page" : "pages"}`}
                  </TableCell>
                  <TableCell className="hidden py-3 sm:table-cell">
                    <StatusBadge status={issue.status} />
                  </TableCell>
                  <TableCell className="py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground group-hover:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpen(issue);
                      }}
                    >
                      Review
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
        </TableBody>
      </Table>
    </div>
  );
}
