"use client";

import { SearchXIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { ChainStrip } from "@/components/intelligence/chain-strip";
import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { fmtDate, fmtDateTime } from "@/components/visibility/format";
import type { ClaimRow } from "@/lib/intelligence/types";
import { Badge, Input, NativeSelect, Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

const ASSOC_LABEL = { brand: "Your brand", competitor: "Competitor", other: "Other" } as const;

export default function ClaimsPage() {
  const intel = useProjectIntelligence();
  const loading = intel.loading || intel.projectLoading;
  const [assoc, setAssoc] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState<ClaimRow | null>(null);
  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return intel.claims.filter(
      (c) =>
        (!assoc || c.associatedWith === assoc) &&
        (!q || `${c.subject} ${c.predicate} ${c.object}`.toLowerCase().includes(q)),
    );
  }, [intel.claims, assoc, query]);

  return (
    <IntelligencePageFrame intel={intel} title="Claims" description="Statements AI engines repeat about you and your competitors (subject – predicate – object), grouped across responses. Repeated claims are what AI engines currently believe; check them for accuracy.">
      <ChainStrip current="claim" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input aria-label="Search claims" placeholder="Search claims…" value={query} onChange={(e) => setQuery(e.target.value)} className="w-64" />
        <NativeSelect aria-label="Associated with" value={assoc} onChange={(e) => setAssoc(e.target.value)} className="w-44">
          <option value="">Anyone</option>
          <option value="brand">Your brand</option>
          <option value="competitor">Competitors</option>
          <option value="other">Other</option>
        </NativeSelect>
        {!loading && <p className="text-muted-foreground text-xs">{rows.length} repeated claims (2+ occurrences)</p>}
      </div>
      {loading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={SearchXIcon}
          tone="neutral"
          title="No repeated claims yet"
          description="This page tracks factual statements AI engines repeat about your brand and competitors, so you can verify what's being said. A claim appears once the same statement shows up in at least two parsed responses — collect more responses to populate it."
        />
      ) : (
        <div className="rounded-xl border">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Claim</TableHead>
                <TableHead className="hidden w-36 md:table-cell">About</TableHead>
                <TableHead className="w-24 text-right">Times</TableHead>
                <TableHead className="hidden w-24 text-right lg:table-cell">Prompts</TableHead>
                <TableHead className="hidden w-28 text-right lg:table-cell">Confidence</TableHead>
                <TableHead className="hidden w-28 xl:table-cell">Last seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.key} className="cursor-pointer" onClick={() => setOpen(c)}>
                  <TableCell className="truncate" title={c.example ?? undefined}>
                    <span className="font-medium capitalize">{c.subject}</span> {c.predicate} {c.object}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <Badge variant={c.associatedWith === "brand" ? "default" : c.associatedWith === "competitor" ? "medium" : "secondary"}>{c.entityName ?? ASSOC_LABEL[c.associatedWith]}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{c.occurrences}</TableCell>
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">{c.prompts}</TableCell>
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">{Math.round(c.confidence * 100)}%</TableCell>
                  <TableCell className="text-muted-foreground hidden text-xs xl:table-cell">{fmtDate(c.lastSeenAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Claim detail: the statement, who it's about, how often engines
          repeat it, and a real example quote from an actual response. */}
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {open && (
            <>
              <SheetHeader className="pr-10">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={open.associatedWith === "brand" ? "default" : open.associatedWith === "competitor" ? "medium" : "secondary"}>
                    {open.entityName ?? ASSOC_LABEL[open.associatedWith]}
                  </Badge>
                </div>
                <SheetTitle className="text-lg leading-snug">
                  <span className="capitalize">{open.subject}</span> {open.predicate} {open.object}
                </SheetTitle>
                <SheetDescription>
                  Repeated {open.occurrences} time{open.occurrences === 1 ? "" : "s"} across {open.responses} response{open.responses === 1 ? "" : "s"} to {open.prompts} prompt{open.prompts === 1 ? "" : "s"} · {Math.round(open.confidence * 100)}% extraction confidence
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                {open.example && (
                  <section className="flex flex-col gap-1.5">
                    <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">As an AI engine put it</h3>
                    <blockquote className="border-primary/30 border-l-2 pl-3 text-sm leading-relaxed">“{open.example}”</blockquote>
                  </section>
                )}
                <section className="flex flex-col gap-1.5">
                  <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Why this matters</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    Repeated claims are what AI engines currently state as fact when answering buyers. Verify it: if it&apos;s
                    wrong or outdated, correcting the pages engines cite is the lever this product measures.
                  </p>
                </section>
                <section className="flex flex-col gap-1.5">
                  <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Follow the trail</h3>
                  <p className="text-sm">
                    <a href="/app/ai-intelligence/ai-responses" className="text-primary underline-offset-4 hover:underline">Read the responses</a>
                    <span className="text-muted-foreground"> that repeat it, or check </span>
                    <a href="/app/ai-intelligence/sources" className="text-primary underline-offset-4 hover:underline">the sources</a>
                    <span className="text-muted-foreground"> those answers cite.</span>
                  </p>
                </section>
                {open.lastSeenAt && (
                  <p className="text-muted-foreground text-xs">Last seen {fmtDateTime(open.lastSeenAt)}</p>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </IntelligencePageFrame>
  );
}
