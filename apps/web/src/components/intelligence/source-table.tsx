"use client";

import { SearchXIcon } from "lucide-react";

import { EmptyState } from "@/components/geo/empty-state";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { SourceRow } from "@/lib/intelligence/types";
import { Badge, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

export function SourceTable({ rows, loading, onOpen }: { rows: SourceRow[]; loading?: boolean; onOpen: (row: SourceRow) => void }) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return <EmptyState icon={SearchXIcon} title="No sources match" description="Adjust the filters or widen the date range." />;
  }
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Source</TableHead>
            <TableHead className="hidden w-32 md:table-cell">Type</TableHead>
            <TableHead className="w-24 text-right">Citations</TableHead>
            <TableHead className="w-20 text-right">Brand</TableHead>
            <TableHead className="hidden w-56 lg:table-cell">Competitors</TableHead>
            <TableHead className="w-28 text-right">Opportunity</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow
              key={r.sourceDomainId}
              className="cursor-pointer"
              role="button"
              tabIndex={0}
              onClick={() => onOpen(r)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpen(r);
                }
              }}
            >
              <TableCell className="truncate font-medium" title={r.domain}>
                {r.domain}
              </TableCell>
              <TableCell className="hidden md:table-cell">
                <Badge variant="secondary">{SOURCE_TYPE_LABEL[r.sourceType]}</Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">{r.citations}</TableCell>
              <TableCell className="text-right tabular-nums">{r.brandCitations}</TableCell>
              <TableCell className="text-muted-foreground hidden truncate text-xs lg:table-cell">
                {Object.entries(r.competitors)
                  .sort((a, b) => b[1] - a[1])
                  .map(([n, c]) => `${n} (${c})`)
                  .join(", ") || "–"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {r.opportunity == null ? <span className="text-muted-foreground">–</span> : Math.round(r.opportunity)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
