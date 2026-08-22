"use client";

import { ArrowDownIcon, ArrowUpIcon, ArrowUpDownIcon, SearchXIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { SeverityBadge, StatusBadge } from "@/components/geo/severity-badge";
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

const COLUMNS: Array<{ key: SortKey | "recommendation" | "action"; label: string; sortable: boolean; className?: string }> = [
  { key: "severity", label: "Severity", sortable: true, className: "w-[5.5rem]" },
  { key: "title", label: "Issue", sortable: true },
  { key: "category", label: "Category", sortable: true, className: "hidden w-36 lg:table-cell" },
  { key: "affected", label: "Affected pages", sortable: true, className: "hidden w-36 text-right xl:table-cell" },
  { key: "recommendation", label: "Recommendation", sortable: false, className: "hidden 2xl:table-cell 2xl:w-[28%]" },
  { key: "status", label: "Status", sortable: true, className: "w-24" },
  { key: "action", label: "Action", sortable: false, className: "w-16" },
];

export function IssueTable({
  issues,
  loading,
  sortKey,
  sortDir,
  onSort,
  onOpen,
  emptyTitle = "No issues match",
  emptyDescription = "Adjust the filters, or run a GEO audit to generate observations.",
}: {
  issues: GeoIssue[];
  loading?: boolean;
  sortKey: SortKey;
  sortDir: SortDirection;
  onSort: (key: SortKey) => void;
  onOpen: (issue: GeoIssue) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (!loading && issues.length === 0) {
    return <EmptyState icon={SearchXIcon} title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map((col) => {
              const active = col.sortable && sortKey === col.key;
              return (
                <TableHead key={col.key} className={col.className} aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                  {col.sortable ? (
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
                  {COLUMNS.map((col) => (
                    <TableCell key={col.key} className={col.className}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : issues.map((issue) => (
                <TableRow key={issue.id} className="cursor-pointer" onClick={() => onOpen(issue)}>
                  <TableCell>
                    <SeverityBadge severity={issue.severity} />
                  </TableCell>
                  <TableCell className="min-w-0">
                    <p className="truncate font-medium" title={issue.title}>
                      {issue.title}
                    </p>
                    {issue.url && (
                      <p className="text-muted-foreground truncate font-mono text-xs" title={issue.url}>
                        {issue.url}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="hidden truncate lg:table-cell">{issue.category}</TableCell>
                  <TableCell className="hidden text-right tabular-nums xl:table-cell">
                    {issue.affectedCount} {issue.affectedCount === 1 ? "page" : "pages"}
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden 2xl:table-cell">
                    <p className="truncate" title={issue.recommendation}>
                      {issue.recommendation}
                    </p>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={issue.status} />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpen(issue);
                      }}
                    >
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
        </TableBody>
      </Table>
    </div>
  );
}
