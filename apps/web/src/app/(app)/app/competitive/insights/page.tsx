"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { CompetitiveInsight, CompetitiveInsightListResponse, InsightType } from "@ai-search-growth-os/types";
import {
  Button,
  NativeSelect,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  TableCell,
  TableRow,
} from "@ai-search-growth-os/ui";

const INSIGHT_TYPES: InsightType[] = [
  "content_advantage",
  "citation_advantage",
  "entity_advantage",
  "evidence_advantage",
  "positioning_advantage",
  "coverage_advantage",
];

export default function CompetitiveInsightsPage() {
  const [insightType, setInsightType] = React.useState("");
  const [impact, setImpact] = React.useState("");
  const res = useProjectResource<CompetitiveInsightListResponse>(
    React.useCallback(
      (pid) =>
        api.competitiveInsights.list(pid, {
          insight_type: insightType || undefined,
          impact: impact || undefined,
          limit: 100,
        }),
      [insightType, impact],
    ),
  );
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<CompetitiveInsight | null>(null);
  const d = res.data;

  const analyze = async () => {
    if (!res.projectId) return;
    setBusy(true);
    setNotice(null);
    try {
      const r = await api.competitiveInsights.analyze(res.projectId);
      setNotice(`Analysed ${r.eligible_responses} responses across ${r.competitors_analyzed} competitors — ${r.insights_written} insights.`);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionFrame
      title="Why Competitors Win"
      description="Observed patterns that coincide with competitors appearing more often in AI answers. These are correlations from measured data — never claims of causation, and never a guarantee that changing something changes rankings."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <Button onClick={() => void analyze()} disabled={!res.projectId || busy}>
          {busy ? "Analysing…" : "Re-analyse"}
        </Button>
      }
    >
      <Toolbar>
        <NativeSelect aria-label="Insight type" value={insightType} onChange={(e) => setInsightType(e.target.value)} className="w-52">
          <option value="">All insight types</option>
          {INSIGHT_TYPES.map((t) => (
            <option key={t} value={t}>
              {label(t)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Impact" value={impact} onChange={(e) => setImpact(e.target.value)} className="w-36">
          <option value="">Any impact</option>
          {["high", "medium", "low"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        {d?.analyzed_at && (
          <span className="text-muted-foreground ml-auto text-xs">Analysed {fmtDateTime(d.analyzed_at)}</span>
        )}
      </Toolbar>
      {notice && <p className="text-muted-foreground mb-3 text-sm">{notice}</p>}
      {d?.note && <p className="text-muted-foreground mb-3 text-xs italic">{d.note}</p>}
      <DataTable
        head={["Insight", "Type", "Impact", "Confidence", "Strength", "Analysed"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No insights yet. Analysis needs enough parsed responses per competitor (10+)." : null}
      >
        {(d?.items ?? []).map((i) => (
          <TableRow key={i.id} className="cursor-pointer" onClick={() => setOpen(i)}>
            <TableCell className="max-w-lg">
              <p className="font-medium">{i.title}</p>
              <p className="text-muted-foreground truncate text-sm" title={i.description}>
                {i.description}
              </p>
            </TableCell>
            <TableCell className="text-sm">{label(i.insight_type)}</TableCell>
            <TableCell>
              <StatusBadge value={i.impact} />
            </TableCell>
            <TableCell>
              <StatusBadge value={i.confidence} />
            </TableCell>
            <TableCell className="tabular-nums">{i.strength}</TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(i.analyzed_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>{open.title}</SheetTitle>
                <SheetDescription>
                  {label(open.insight_type)} · impact {open.impact} · confidence {open.confidence}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="Observed pattern">
                  <p className="text-sm">{open.description}</p>
                </DrawerSection>
                <DrawerSection title="Evidence">
                  <EvidenceList evidence={open.evidence} />
                </DrawerSection>
                <p className="text-muted-foreground text-xs">
                  Window: last {open.window_days} days · analysed {fmtDateTime(open.analyzed_at)} · {open.analysis_version}
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
