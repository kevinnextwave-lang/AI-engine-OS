"use client";

import { ExternalLinkIcon, SearchXIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { ChainStrip } from "@/components/intelligence/chain-strip";
import { CitationDrawer } from "@/components/intelligence/citation-drawer";
import { CitationsChart } from "@/components/intelligence/citations-chart";
import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { SourceDrawer } from "@/components/intelligence/source-drawer";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { useProject } from "@/components/project-provider";
import { fmtDateTime } from "@/components/visibility/format";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import { citationRows } from "@/lib/intelligence/mappers";
import type { CitationRow as CitationRowType, SourceRow } from "@/lib/intelligence/types";
import { providerLabel } from "@/lib/visibility/labels";
import { Badge, Button, Input, NativeSelect, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

export default function CitationsPage() {
  const intel = useProjectIntelligence();
  const { current } = useProject();
  const loading = intel.loading || intel.projectLoading;
  const [query, setQuery] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [relationship, setRelationship] = React.useState("");
  const [openSource, setOpenSource] = React.useState<SourceRow | null>(null);
  const [openCitation, setOpenCitation] = React.useState<CitationRowType | null>(null);
  const rows = React.useMemo(() => {
    const all = citationRows(intel.raw?.citations ?? []);
    const q = query.trim().toLowerCase();
    return all.filter(
      (c) =>
        (!provider || c.provider === provider) &&
        (!relationship || c.relationships.some((r) => r.relationship === relationship)) &&
        (!q || (c.url ?? c.domain ?? "").toLowerCase().includes(q) || c.prompt.toLowerCase().includes(q)),
    );
  }, [intel.raw, query, provider, relationship]);

  return (
    <IntelligencePageFrame intel={intel} title="Citations" description="Each citation an AI engine made while answering your prompts: the URL, the prompt, the engine, and whether it relates to your brand or a competitor.">
      <ChainStrip current="citation" />
      <CitationsChart
        citations={intel.raw?.citations ?? []}
        total={intel.raw?.citationsTotal ?? 0}
        windowDays={intel.window === "30d" ? 30 : intel.window === "90d" ? 90 : 180}
        windowLabel={`Last ${intel.window.replace("d", " days")}`}
        loading={loading}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input aria-label="Search citations" placeholder="Search URL or prompt…" value={query} onChange={(e) => setQuery(e.target.value)} className="w-64" />
        <NativeSelect aria-label="AI engine" value={provider} onChange={(e) => setProvider(e.target.value)} className="w-40">
          <option value="">All AI engines</option>
          {intel.providerKeys.map((p) => (
            <option key={p} value={p}>
              {providerLabel(p)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Relationship" value={relationship} onChange={(e) => setRelationship(e.target.value)} className="w-44">
          <option value="">Any relationship</option>
          <option value="brand">Related to your brand</option>
          <option value="competitor">Related to a competitor</option>
        </NativeSelect>
        {!loading && intel.raw && (
          <p className="text-muted-foreground text-xs">
            {rows.length} shown · {intel.raw.citationsTotal} in this period{intel.raw.citationsTotal > intel.raw.citations.length ? ` (newest ${intel.raw.citations.length} loaded)` : ""}
          </p>
        )}
      </div>
      {loading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState icon={SearchXIcon} title="No citations match" description="Adjust the filters or widen the date range." />
      ) : (
        <div className="rounded-xl border">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Cited URL</TableHead>
                <TableHead className="hidden w-28 md:table-cell">Type</TableHead>
                <TableHead className="hidden lg:table-cell lg:w-[28%]">Prompt</TableHead>
                <TableHead className="w-28">Engine</TableHead>
                <TableHead className="hidden w-40 xl:table-cell">Relates to</TableHead>
                <TableHead className="hidden w-40 md:table-cell">When</TableHead>
                <TableHead className="w-20">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
<TableRow key={c.id} className="cursor-pointer" onClick={() => setOpenCitation(c)}>
                  <TableCell className="truncate">
                    {c.url ? (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-primary inline-flex max-w-full items-center gap-1 underline-offset-4 hover:underline"
                        title={c.url}
                      >
                        {/* Domain leads; the path stays visible but quiet so
                            long URLs stop dominating the table. */}
                        {(() => {
                          try {
                            const u = new URL(c.url);
                            const rest = `${u.pathname}${u.search}`;
                            return (
                              <span className="truncate">
                                <span className="font-medium">{u.hostname.replace(/^www\./, "")}</span>
                                {rest !== "/" && <span className="text-muted-foreground">{rest}</span>}
                              </span>
                            );
                          } catch {
                            return <span className="truncate">{c.url}</span>;
                          }
                        })()}
                        <ExternalLinkIcon className="size-3 shrink-0" aria-hidden="true" />
                      </a>
                    ) : (
                      <span>{c.domain ?? "–"}</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{c.sourceType ? <Badge variant="secondary">{SOURCE_TYPE_LABEL[c.sourceType]}</Badge> : "–"}</TableCell>
                  <TableCell className="hidden truncate lg:table-cell" title={c.prompt}>
                    {c.prompt}
                  </TableCell>
                  <TableCell className="text-xs">
                    {c.providerLabel}
                    {c.model && <span className="text-muted-foreground block truncate font-mono text-[11px]">{c.model}</span>}
                  </TableCell>
                  <TableCell className="hidden xl:table-cell">
                    <span className="flex flex-wrap gap-1">
                      {c.relationships.map((r) => (
                        <Badge key={r.name + r.relationship} variant={r.relationship === "brand" ? "default" : "medium"} title={`confidence ${r.confidence}`}>
                          {r.name}
                        </Badge>
                      ))}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden text-xs md:table-cell">{fmtDateTime(c.citedAt)}</TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setOpenCitation(c); }}>
                      Trail
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <CitationDrawer
        citation={openCitation}
        projectWebsiteUrl={current?.primary_domain?.url ?? null}
        onClose={() => setOpenCitation(null)}
        onOpenSource={(sourceDomainId) => {
          const row = intel.sources.find((s) => s.sourceDomainId === sourceDomainId);
          if (row) {
            setOpenCitation(null);
            setOpenSource(row);
          }
        }}
      />
      <SourceDrawer row={openSource} projectId={current?.id ?? null} range={intel.windowRange} live={intel.source === "api"} mockCitations={intel.raw?.citations ?? []} onClose={() => setOpenSource(null)} />
    </IntelligencePageFrame>
  );
}
