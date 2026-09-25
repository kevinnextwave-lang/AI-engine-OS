"use client";

import { MessageSquareTextIcon } from "lucide-react";

import { EmptyState } from "@/components/geo/empty-state";
import { fmtDateTime, fmtValue } from "@/components/visibility/format";
import { providerLabel } from "@/lib/visibility/labels";
import type { PromptPerformanceRow } from "@/lib/visibility/types";
import { Badge, Progress, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

export function PromptTable({
  rows,
  loading,
  onOpen,
  limit,
  emptyTitle = "No prompt has a parsed response in this period",
  emptyDescription = "Run a prompt set to collect AI answers; each prompt's measured mention and recommendation rates appear here.",
}: {
  rows: PromptPerformanceRow[];
  loading?: boolean;
  onOpen: (row: PromptPerformanceRow) => void;
  limit?: number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState icon={MessageSquareTextIcon} tone="neutral" title={emptyTitle} description={emptyDescription} />
    );
  }
  const shown = limit ? rows.slice(0, limit) : rows;
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Prompt</TableHead>
            <TableHead className="hidden w-36 lg:table-cell">Category</TableHead>
            <TableHead className="w-40">Brand mention</TableHead>
            <TableHead className="hidden w-32 text-right md:table-cell">Recommendation</TableHead>
            <TableHead className="hidden w-24 text-right md:table-cell">Position</TableHead>
            <TableHead className="hidden w-44 xl:table-cell">Last run</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((r) => (
            <TableRow
              key={r.id}
              className="cursor-pointer"
              tabIndex={0}
              role="button"
              aria-label={`Open response history for: ${r.prompt}`}
              onClick={() => onOpen(r)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpen(r);
                }
              }}
            >
              <TableCell className="truncate" title={r.prompt}>
                {r.prompt}
                <span className="text-muted-foreground ml-2 text-xs tabular-nums">n={r.sampleSize}</span>
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <Badge variant="secondary">{r.categoryLabel}</Badge>
              </TableCell>
              <TableCell title={`${r.mentions} of ${r.sampleSize} responses`}>
                {r.mentionRate == null ? (
                  <span className="text-muted-foreground tabular-nums" title="Fewer than 5 responses">
                    {r.mentions}/{r.sampleSize}
                  </span>
                ) : (
                  // Same anatomy as the engine table: number + comparative bar.
                  <div className="flex items-center gap-2">
                    <span className="w-10 text-right tabular-nums">{fmtValue(r.mentionRate, "percent")}</span>
                    <Progress
                      value={r.mentionRate}
                      className="flex-1"
                      aria-label={`Brand mention rate for this prompt: ${r.mentionRate}%`}
                    />
                  </div>
                )}
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.recommendationRate, "percent")}</TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.averagePosition, "position")}</TableCell>
              <TableCell className="text-muted-foreground hidden truncate text-xs xl:table-cell">
                {r.lastRun ? `${fmtDateTime(r.lastRun)}${r.lastRunProvider ? ` · ${providerLabel(r.lastRunProvider)}` : ""}` : "–"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
