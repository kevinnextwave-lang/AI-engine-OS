"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { ContentGap, ContentGapListResponse, ContentGapType } from "@ai-search-growth-os/types";
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

const GAP_TYPES: ContentGapType[] = [
  "missing_topic",
  "weak_topic",
  "missing_comparison",
  "missing_use_case",
  "missing_faq",
  "missing_evidence",
  "missing_product_detail",
];
const GAP_STATUSES = ["new", "reviewing", "accepted", "dismissed", "in_progress", "completed"] as const;

export default function CompetitiveContentGapsPage() {
  const [gapType, setGapType] = React.useState("");
  const [status, setStatus] = React.useState("");
  const res = useProjectResource<ContentGapListResponse>(
    React.useCallback(
      (pid) =>
        api.contentGaps.list(pid, {
          gap_type: gapType || undefined,
          status: status || undefined,
          limit: 100,
        }),
      [gapType, status],
    ),
  );
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<ContentGap | null>(null);
  const d = res.data;
  const liveOpen = open ? (d?.items.find((g) => g.id === open.id) ?? open) : null;

  const analyze = async () => {
    if (!res.projectId) return;
    setBusy("analyze");
    setNotice(null);
    try {
      const r = await api.contentGaps.analyze(res.projectId);
      setNotice(`Analysed ${r.topics_analyzed} topics against ${r.pages_considered} pages — ${r.gaps_written} gaps.`);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(null);
    }
  };

  const setGapStatus = async (gap: ContentGap, next: string) => {
    setBusy(gap.id);
    try {
      await api.contentGaps.update(gap.id, { status: next });
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionFrame
      title="Competitive Content Gaps"
      description="Topics where AI answers lean on competitors while your site has little or nothing to say. Scores rank opportunity from measured coverage differences; creating content is your call — nothing here is auto-generated or guaranteed to change rankings."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <Button onClick={() => void analyze()} disabled={!res.projectId || busy !== null}>
          {busy === "analyze" ? "Analysing…" : "Re-analyse"}
        </Button>
      }
    >
      <Toolbar>
        <NativeSelect aria-label="Gap type" value={gapType} onChange={(e) => setGapType(e.target.value)} className="w-52">
          <option value="">All gap types</option>
          {GAP_TYPES.map((t) => (
            <option key={t} value={t}>
              {label(t)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
          <option value="">Any status</option>
          {GAP_STATUSES.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </NativeSelect>
        {d?.analyzed_at && (
          <span className="text-muted-foreground ml-auto text-xs">Analysed {fmtDateTime(d.analyzed_at)}</span>
        )}
      </Toolbar>
      {notice && <p className="text-muted-foreground mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Topic", "Gap type", "Score", "Confidence", "Status", "Analysed"]}
        loading={res.loading}
        empty={
          d && d.items.length === 0
            ? {
                title: "No content gaps found",
                description:
                  "Content gaps are topics where AI answers draw on competitor content but not yours. Nothing matches the current filters — either the filters are narrow, or the analysis hasn't found gaps in the collected responses yet.",
              }
            : null
        }
      >
        {(d?.items ?? []).map((g) => (
          <TableRow key={g.id} className="cursor-pointer" onClick={() => setOpen(g)}>
            <TableCell className="max-w-md font-medium">{g.topic}</TableCell>
            <TableCell className="text-sm">{label(g.gap_type)}</TableCell>
            <TableCell className="tabular-nums">{g.opportunity_score}</TableCell>
            <TableCell>
              <StatusBadge value={g.confidence} />
            </TableCell>
            <TableCell>
              <StatusBadge value={g.status} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(g.analyzed_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={liveOpen !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {liveOpen && (
            <>
              <SheetHeader>
                <SheetTitle>{liveOpen.topic}</SheetTitle>
                <SheetDescription>
                  {label(liveOpen.gap_type)} · score {liveOpen.opportunity_score} · confidence {liveOpen.confidence}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="Status">
                  <NativeSelect
                    aria-label="Gap status"
                    value={liveOpen.status}
                    disabled={busy !== null}
                    onChange={(e) => void setGapStatus(liveOpen, e.target.value)}
                    className="w-48"
                  >
                    {GAP_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </NativeSelect>
                </DrawerSection>
                <DrawerSection title="Competitor evidence">
                  <EvidenceList evidence={liveOpen.competitor_evidence} />
                </DrawerSection>
                <DrawerSection title="Your coverage">
                  <EvidenceList evidence={liveOpen.customer_coverage} />
                </DrawerSection>
                <p className="text-muted-foreground text-xs">
                  Window: last {liveOpen.window_days} days · analysed {fmtDateTime(liveOpen.analyzed_at)}
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
