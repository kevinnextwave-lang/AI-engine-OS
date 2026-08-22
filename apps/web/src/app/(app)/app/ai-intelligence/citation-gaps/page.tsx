"use client";

import * as React from "react";

import { GapDrawer } from "@/components/intelligence/gap-drawer";
import { GapTable } from "@/components/intelligence/gap-table";
import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { useProject } from "@/components/project-provider";
import { fmtDateTime } from "@/components/visibility/format";
import { GAP_STATUS_LABEL, GAP_TYPE_LABEL, SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { CitationGap, DomainType, GapStatus, GapType } from "@ai-search-growth-os/types";
import { Button, Input, NativeSelect } from "@ai-search-growth-os/ui";

export default function CitationGapsPage() {
  const intel = useProjectIntelligence();
  const { current } = useProject();
  const loading = intel.loading || intel.projectLoading;
  const [open, setOpen] = React.useState<CitationGap | null>(null);
  const [gapType, setGapType] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [sourceType, setSourceType] = React.useState("");
  const [competitor, setCompetitor] = React.useState("");
  const [minScore, setMinScore] = React.useState("");
  const gaps = React.useMemo(
    () =>
      intel.gaps.filter(
        (g) =>
          (!gapType || g.gap_type === gapType) &&
          (!status || g.status === status) &&
          (!sourceType || g.source_type === sourceType) &&
          (!competitor || competitor in g.competitors) &&
          (!minScore || g.opportunity_score >= Number(minScore)),
      ),
    [intel.gaps, gapType, status, sourceType, competitor, minScore],
  );
  const liveOpen = open ? (intel.gaps.find((g) => g.id === open.id) ?? open) : null;

  return (
    <IntelligencePageFrame intel={intel} title="Citation Gaps" description="Sources that appear in relevant AI answers but rarely cite your brand. Scores are transparent opportunity indicators, not guarantees; every gap shows its evidence and a neutral recommendation.">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <NativeSelect aria-label="Gap type" value={gapType} onChange={(e) => setGapType(e.target.value)} className="w-44">
          <option value="">All gap types</option>
          {(Object.keys(GAP_TYPE_LABEL) as GapType[]).map((t) => (
            <option key={t} value={t}>
              {GAP_TYPE_LABEL[t]}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-36">
          <option value="">Any status</option>
          {(Object.keys(GAP_STATUS_LABEL) as GapStatus[]).map((s) => (
            <option key={s} value={s}>
              {GAP_STATUS_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Source type" value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="w-40">
          <option value="">All source types</option>
          {[...new Set(intel.gaps.map((g) => g.source_type))].sort().map((t) => (
            <option key={t} value={t}>
              {SOURCE_TYPE_LABEL[t as DomainType]}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Competitor" value={competitor} onChange={(e) => setCompetitor(e.target.value)} className="w-44">
          <option value="">Any competitor</option>
          {intel.competitorNames.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </NativeSelect>
        <Input aria-label="Minimum score" type="number" min={0} max={100} placeholder="Min score" value={minScore} onChange={(e) => setMinScore(e.target.value)} className="w-32" />
        <div className="ml-auto flex items-center gap-2">
          {intel.gapSummary?.analyzed_at && <span className="text-muted-foreground text-xs">Analysed {fmtDateTime(intel.gapSummary.analyzed_at)}</span>}
          <Button size="sm" variant="outline" onClick={() => void intel.actions.analyzeGaps()} disabled={intel.source !== "api" || intel.busy === "analyze"}>
            {intel.busy === "analyze" ? "Analysing…" : "Re-analyse"}
          </Button>
        </div>
      </div>
      <GapTable gaps={gaps} loading={loading} onOpen={setOpen} />
      <GapDrawer
        gap={liveOpen}
        brandName={intel.brandName}
        projectId={current?.id ?? null}
        live={intel.source === "api"}
        mockCitations={intel.raw?.citations ?? []}
        busy={intel.busy === "gap"}
        onUpdate={intel.actions.updateGap}
        onClose={() => setOpen(null)}
      />
    </IntelligencePageFrame>
  );
}
