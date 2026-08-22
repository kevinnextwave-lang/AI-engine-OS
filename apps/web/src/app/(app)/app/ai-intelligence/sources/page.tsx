"use client";

import * as React from "react";

import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { SourceDrawer } from "@/components/intelligence/source-drawer";
import { SourceTable } from "@/components/intelligence/source-table";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { useProject } from "@/components/project-provider";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { SourceRow } from "@/lib/intelligence/types";
import type { DomainType } from "@ai-search-growth-os/types";
import { Input, NativeSelect } from "@ai-search-growth-os/ui";

export default function SourcesPage() {
  const intel = useProjectIntelligence();
  const { current } = useProject();
  const loading = intel.loading || intel.projectLoading;
  const [open, setOpen] = React.useState<SourceRow | null>(null);
  const [sourceType, setSourceType] = React.useState("");
  const [minCitations, setMinCitations] = React.useState("");
  const [competitor, setCompetitor] = React.useState("");
  const [minOpportunity, setMinOpportunity] = React.useState("");
  const types = React.useMemo(() => [...new Set(intel.sources.map((s) => s.sourceType))].sort(), [intel.sources]);
  const rows = React.useMemo(
    () =>
      intel.sources.filter(
        (s) =>
          (!sourceType || s.sourceType === sourceType) &&
          (!minCitations || s.citations >= Number(minCitations)) &&
          (!competitor || competitor in s.competitors) &&
          (!minOpportunity || (s.opportunity ?? -1) >= Number(minOpportunity)),
      ),
    [intel.sources, sourceType, minCitations, competitor, minOpportunity],
  );

  return (
    <IntelligencePageFrame intel={intel} title="Sources" description="Every source domain cited in this period, with how many citations relate to your brand and to competitors, and the citation-gap opportunity score where one exists. The date range is set in the header.">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <NativeSelect aria-label="Source type" value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="w-40">
          <option value="">All source types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {SOURCE_TYPE_LABEL[t as DomainType]}
            </option>
          ))}
        </NativeSelect>
        <Input aria-label="Minimum citations" type="number" min={0} placeholder="Min citations" value={minCitations} onChange={(e) => setMinCitations(e.target.value)} className="w-36" />
        <NativeSelect aria-label="Competitor" value={competitor} onChange={(e) => setCompetitor(e.target.value)} className="w-44">
          <option value="">Any competitor</option>
          {intel.competitorNames.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </NativeSelect>
        <Input aria-label="Minimum opportunity score" type="number" min={0} max={100} placeholder="Min opportunity" value={minOpportunity} onChange={(e) => setMinOpportunity(e.target.value)} className="w-40" />
        {!loading && (
          <p className="text-muted-foreground text-xs">
            {rows.length} of {intel.sources.length} sources
          </p>
        )}
      </div>
      <SourceTable rows={rows} loading={loading} onOpen={setOpen} />
      <SourceDrawer row={open} projectId={current?.id ?? null} range={intel.windowRange} live={intel.source === "api"} mockCitations={intel.raw?.citations ?? []} onClose={() => setOpen(null)} />
    </IntelligencePageFrame>
  );
}
