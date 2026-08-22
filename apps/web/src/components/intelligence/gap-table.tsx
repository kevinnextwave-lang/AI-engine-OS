"use client";

import { SearchXIcon } from "lucide-react";

import { EmptyState } from "@/components/geo/empty-state";
import { CONFIDENCE_LABEL, GAP_STATUS_LABEL, GAP_TYPE_LABEL, SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { CitationGap } from "@ai-search-growth-os/types";
import { Badge, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

const PRIORITY_VARIANT = { high: "high", medium: "medium", low: "muted" } as const;

export function GapTable({ gaps, loading, onOpen }: { gaps: CitationGap[]; loading?: boolean; onOpen: (gap: CitationGap) => void }) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (gaps.length === 0) {
    return <EmptyState icon={SearchXIcon} title="No citation gaps match" description="Adjust the filters, or run the analysis after collecting more AI responses." />;
  }
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Source</TableHead>
            <TableHead className="hidden w-40 lg:table-cell">Gap</TableHead>
            <TableHead className="w-24 text-right">Score</TableHead>
            <TableHead className="hidden w-20 text-right md:table-cell">Brand</TableHead>
            <TableHead className="hidden w-28 text-right md:table-cell">Competitors</TableHead>
            <TableHead className="hidden w-36 xl:table-cell">Confidence</TableHead>
            <TableHead className="w-28">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {gaps.map((g) => (
            <TableRow
              key={g.id}
              className="cursor-pointer"
              role="button"
              tabIndex={0}
              onClick={() => onOpen(g)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpen(g);
                }
              }}
            >
              <TableCell className="truncate">
                <span className="font-medium">{g.display_name}</span>
                <span className="text-muted-foreground ml-2 text-xs">{SOURCE_TYPE_LABEL[g.source_type]}</span>
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <Badge variant="secondary">{GAP_TYPE_LABEL[g.gap_type]}</Badge>
              </TableCell>
              <TableCell className="text-right">
                <Badge variant={PRIORITY_VARIANT[g.priority]} className="tabular-nums">
                  {Math.round(g.opportunity_score)}
                </Badge>
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">{g.brand_citations}</TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">{g.competitor_citations}</TableCell>
              <TableCell className="text-muted-foreground hidden text-xs xl:table-cell">{CONFIDENCE_LABEL[g.confidence]}</TableCell>
              <TableCell className="text-xs">{GAP_STATUS_LABEL[g.status]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
