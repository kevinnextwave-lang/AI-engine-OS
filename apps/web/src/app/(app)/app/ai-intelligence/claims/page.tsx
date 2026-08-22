"use client";

import { SearchXIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { fmtDate } from "@/components/visibility/format";
import { Badge, Input, NativeSelect, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

const ASSOC_LABEL = { brand: "Your brand", competitor: "Competitor", other: "Other" } as const;

export default function ClaimsPage() {
  const intel = useProjectIntelligence();
  const loading = intel.loading || intel.projectLoading;
  const [assoc, setAssoc] = React.useState("");
  const [query, setQuery] = React.useState("");
  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return intel.claims.filter((c) => (!assoc || c.associatedWith === assoc) && (!q || `${c.subject} ${c.predicate} ${c.object}`.includes(q)));
  }, [intel.claims, assoc, query]);

  return (
    <IntelligencePageFrame intel={intel} title="Claims" description="Statements AI engines repeat about you and your competitors (subject – predicate – object), grouped across responses. Repeated claims are what AI engines currently believe; check them for accuracy.">
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
        <EmptyState icon={SearchXIcon} title="No repeated claims" description="Claims appear here once the same statement shows up in at least two AI responses." />
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
                <TableRow key={c.key}>
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
    </IntelligencePageFrame>
  );
}
