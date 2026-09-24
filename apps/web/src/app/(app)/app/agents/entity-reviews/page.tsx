"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { EntityOptimizationReview, EntityReviewListResponse, EntityReviewStatus } from "@ai-search-growth-os/types";
import {
  NativeSelect,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  TableCell,
  TableRow,
} from "@ai-search-growth-os/ui";

const REVIEW_STATUSES: EntityReviewStatus[] = ["draft", "reviewing", "approved", "completed", "archived"];

export default function EntityReviewsPage() {
  const [status, setStatus] = React.useState("");
  const [entityType, setEntityType] = React.useState("");
  const res = useProjectResource<EntityReviewListResponse>(
    React.useCallback(
      (pid) =>
        api.entityReviews.list(pid, {
          status: status || undefined,
          entity_type: entityType || undefined,
          limit: 100,
        }),
      [status, entityType],
    ),
  );
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<EntityOptimizationReview | null>(null);
  const d = res.data;
  const liveOpen = open ? (d?.items.find((r) => r.id === open.id) ?? open) : null;
  const entityTypes = React.useMemo(
    // Include the selected type even when the filtered result no longer
    // contains it, so the select never silently shows "All" while filtering.
    () =>
      [...new Set([...(d?.items ?? []).map((r) => r.entity_type), ...(entityType ? [entityType] : [])])].sort(),
    [d, entityType],
  );

  const setReviewStatus = async (review: EntityOptimizationReview, next: EntityReviewStatus) => {
    setBusy(true);
    try {
      await api.entityReviews.setStatus(review.id, next);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionFrame
      title="Entity Reviews"
      description="Structured-data reviews from the Entity Optimization agent: organization, product, service and people entities plus cross-page consistency. Recommendations describe what your pages state — never guarantees about how engines will interpret changes — and all modifications require your approval."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
    >
      <Toolbar>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
          <option value="">Any status</option>
          {REVIEW_STATUSES.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Entity type" value={entityType} onChange={(e) => setEntityType(e.target.value)} className="w-44">
          <option value="">All entity types</option>
          {entityTypes.map((t) => (
            <option key={t} value={t}>
              {label(t)}
            </option>
          ))}
        </NativeSelect>
      </Toolbar>
      {notice && <p className="text-destructive mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Review", "Entity type", "Findings", "Confidence", "Status", "Analysed"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No entity reviews yet — run the Entity Optimization agent." : null}
      >
        {(d?.items ?? []).map((r) => (
          <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r)}>
            <TableCell className="font-medium">{label(r.review_key.replaceAll(":", " · "))}</TableCell>
            <TableCell className="text-sm">{label(r.entity_type)}</TableCell>
            <TableCell className="tabular-nums">{r.findings.length}</TableCell>
            <TableCell>
              <StatusBadge value={r.confidence} />
            </TableCell>
            <TableCell>
              <StatusBadge value={r.status} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(r.analyzed_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={liveOpen !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
          {liveOpen && (
            <>
              <SheetHeader>
                <SheetTitle>{label(liveOpen.review_key.replaceAll(":", " · "))}</SheetTitle>
                <SheetDescription>
                  {label(liveOpen.entity_type)} · confidence {liveOpen.confidence} · analysed {fmtDateTime(liveOpen.analyzed_at)}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="Status">
                  <NativeSelect
                    aria-label="Review status"
                    value={liveOpen.status}
                    disabled={busy}
                    onChange={(e) => void setReviewStatus(liveOpen, e.target.value as EntityReviewStatus)}
                    className="w-48"
                  >
                    {REVIEW_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </NativeSelect>
                </DrawerSection>
                {liveOpen.findings.length > 0 && (
                  <DrawerSection title={`Findings (${liveOpen.findings.length})`}>
                    <div className="flex flex-col gap-2">
                      {liveOpen.findings.map((f, i) => (
                        <div key={i} className="rounded-lg border p-3">
                          <EvidenceList evidence={f} />
                        </div>
                      ))}
                    </div>
                  </DrawerSection>
                )}
                {liveOpen.recommendations.length > 0 && (
                  <DrawerSection title={`Recommendations (${liveOpen.recommendations.length})`}>
                    <div className="flex flex-col gap-2">
                      {liveOpen.recommendations.map((r, i) => (
                        <div key={i} className="rounded-lg border p-3">
                          <EvidenceList evidence={r} />
                        </div>
                      ))}
                    </div>
                  </DrawerSection>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
