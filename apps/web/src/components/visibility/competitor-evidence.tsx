"use client";

/**
 * Evidence sections for the Competitors experience, built from observed
 * citations (the citation-intelligence window):
 *
 * - CitationOverlap: the sources competitor-related answers cite, side by
 *   side with your own citations from the same source.
 * - CompetitorPrompts: the prompts whose answers cited competitor-related
 *   material, deep-linking into the full answer.
 *
 * Both accept a selected competitor to narrow the evidence — the drill-down
 * from a comparison row to its proof.
 */

import Link from "next/link";
import * as React from "react";

import { rowButtonProps } from "@/lib/a11y";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { CitationRow, SourceRow } from "@/lib/intelligence/types";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ai-search-growth-os/ui";
import { SearchXIcon } from "lucide-react";

export function CitationOverlap({
  sources,
  selectedCompetitor,
  loading,
  onOpenSource,
}: {
  sources: SourceRow[];
  selectedCompetitor: string | null;
  loading: boolean;
  onOpenSource: (row: SourceRow) => void;
}) {
  const rows = React.useMemo(() => {
    const relevant = sources.filter((s) =>
      selectedCompetitor ? (s.competitors[selectedCompetitor] ?? 0) > 0 : s.competitorCitations > 0,
    );
    return [...relevant].sort((a, b) =>
      selectedCompetitor
        ? (b.competitors[selectedCompetitor] ?? 0) - (a.competitors[selectedCompetitor] ?? 0)
        : b.competitorCitations - a.competitorCitations,
    );
  }, [sources, selectedCompetitor]);

  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={SearchXIcon}
        tone="neutral"
        title={selectedCompetitor ? `No sources cited for ${selectedCompetitor}` : "No competitor citations observed"}
        description="This fills in when AI answers cite sources linked to a configured competitor. Collect more responses, or widen the analysis window on the Citation Intelligence pages."
      />
    );
  }
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Source</TableHead>
            <TableHead className="hidden w-28 md:table-cell">Type</TableHead>
            <TableHead className="w-40 text-right">
              {selectedCompetitor ? `${selectedCompetitor} citations` : "Competitor citations"}
            </TableHead>
            <TableHead className="w-32 text-right">Your citations</TableHead>
            <TableHead className="hidden w-52 xl:table-cell">Who&apos;s cited</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((s) => (
            <TableRow
              key={s.sourceDomainId}
              className="cursor-pointer"
              {...rowButtonProps(() => onOpenSource(s), `Open source profile for ${s.domain}`)}
            >
              <TableCell className="truncate font-medium" title={s.domain}>
                {s.displayName || s.domain}
              </TableCell>
              <TableCell className="hidden md:table-cell">
                <Badge variant="secondary">{SOURCE_TYPE_LABEL[s.sourceType]}</Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {selectedCompetitor ? (s.competitors[selectedCompetitor] ?? 0) : s.competitorCitations}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {s.brandCitations > 0 ? (
                  s.brandCitations
                ) : (
                  <span className="text-warning font-medium" title="Competitors are cited from this source; you are not">
                    0
                  </span>
                )}
              </TableCell>
              <TableCell className="hidden xl:table-cell">
                <span className="flex flex-wrap gap-1">
                  {Object.entries(s.competitors)
                    .filter(([, n]) => n > 0)
                    .slice(0, 3)
                    .map(([name]) => (
                      <Badge key={name} variant="medium">
                        {name}
                      </Badge>
                    ))}
                  {s.brandCitations > 0 && <Badge variant="default">You</Badge>}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface PromptEvidence {
  promptId: string;
  prompt: string;
  competitors: string[];
  citations: number;
}

export function CompetitorPrompts({
  citations,
  selectedCompetitor,
  loading,
}: {
  citations: CitationRow[];
  selectedCompetitor: string | null;
  loading: boolean;
}) {
  const rows = React.useMemo(() => {
    const byPrompt = new Map<string, PromptEvidence>();
    for (const c of citations) {
      const rels = c.relationships.filter((r) => r.relationship === "competitor");
      if (rels.length === 0) continue;
      if (selectedCompetitor && !rels.some((r) => r.name === selectedCompetitor)) continue;
      const entry = byPrompt.get(c.promptId) ?? { promptId: c.promptId, prompt: c.prompt, competitors: [], citations: 0 };
      entry.citations += 1;
      for (const r of rels) if (!entry.competitors.includes(r.name)) entry.competitors.push(r.name);
      byPrompt.set(c.promptId, entry);
    }
    return [...byPrompt.values()].sort((a, b) => b.citations - a.citations);
  }, [citations, selectedCompetitor]);

  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={SearchXIcon}
        tone="neutral"
        title={
          selectedCompetitor
            ? `No prompts with ${selectedCompetitor}-related citations`
            : "No prompts with competitor-related citations"
        }
        description="This lists the prompts whose stored answers cited sources linked to a competitor. It fills in as responses with such citations are collected."
      />
    );
  }
  return (
    <div className="rounded-xl border">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Prompt</TableHead>
            <TableHead className="hidden w-56 lg:table-cell">Competitors cited</TableHead>
            <TableHead className="w-24 text-right">Citations</TableHead>
            <TableHead className="w-32">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.promptId}>
              <TableCell className="truncate" title={r.prompt}>
                {r.prompt}
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <span className="flex flex-wrap gap-1">
                  {r.competitors.map((name) => (
                    <Badge key={name} variant="medium">
                      {name}
                    </Badge>
                  ))}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{r.citations}</TableCell>
              <TableCell className="text-right">
                <Button asChild size="sm" variant="ghost">
                  <Link href={`/app/ai-visibility/prompts?prompt=${r.promptId}`}>Read answer</Link>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
