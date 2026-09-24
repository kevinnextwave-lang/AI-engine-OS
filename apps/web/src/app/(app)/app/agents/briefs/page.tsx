"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { ContentBrief, ContentBriefListResponse, ContentBriefStatus } from "@ai-search-growth-os/types";
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

const BRIEF_STATUSES: ContentBriefStatus[] = [
  "draft",
  "reviewing",
  "approved",
  "in_progress",
  "completed",
  "archived",
];

export default function ContentBriefsPage() {
  const [status, setStatus] = React.useState("");
  const res = useProjectResource<ContentBriefListResponse>(
    React.useCallback(
      (pid) => api.contentBriefs.list(pid, { status: status || undefined, limit: 100 }),
      [status],
    ),
  );
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<ContentBrief | null>(null);
  const d = res.data;
  const liveOpen = open ? (d?.items.find((b) => b.id === open.id) ?? open) : null;

  const setBriefStatus = async (brief: ContentBrief, next: ContentBriefStatus) => {
    setBusy(true);
    try {
      await api.contentBriefs.update(brief.id, { status: next });
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionFrame
      title="Content Briefs"
      description="Structured briefs the Content Strategy agent produced from high-scoring content gaps: what to create, for whom, and what information and evidence it needs. Briefs contain [FILL] placeholders where only you can supply real facts — nothing is invented."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
    >
      <Toolbar>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
          <option value="">Any status</option>
          {BRIEF_STATUSES.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </NativeSelect>
      </Toolbar>
      {notice && <p className="text-destructive mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Brief", "Content type", "Confidence", "Status", "Updated"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No briefs yet — run the Content Strategy agent once content gaps exist." : null}
      >
        {(d?.items ?? []).map((b) => (
          <TableRow key={b.id} className="cursor-pointer" onClick={() => setOpen(b)}>
            <TableCell className="max-w-lg">
              <p className="font-medium">{b.title}</p>
              <p className="text-muted-foreground truncate text-sm" title={b.objective}>
                {b.objective}
              </p>
            </TableCell>
            <TableCell className="text-sm">{label(b.content_type)}</TableCell>
            <TableCell>
              <StatusBadge value={b.confidence} />
            </TableCell>
            <TableCell>
              <StatusBadge value={b.status} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(b.updated_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={liveOpen !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
          {liveOpen && (
            <>
              <SheetHeader>
                <SheetTitle>{liveOpen.title}</SheetTitle>
                <SheetDescription>
                  {label(liveOpen.content_type)} · confidence {liveOpen.confidence}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="Status">
                  <NativeSelect
                    aria-label="Brief status"
                    value={liveOpen.status}
                    disabled={busy}
                    onChange={(e) => void setBriefStatus(liveOpen, e.target.value as ContentBriefStatus)}
                    className="w-48"
                  >
                    {BRIEF_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </NativeSelect>
                </DrawerSection>
                <DrawerSection title="Objective">
                  <p className="text-sm">{liveOpen.objective}</p>
                </DrawerSection>
                <DrawerSection title="Audience & intent">
                  <p className="text-sm">{liveOpen.audience}</p>
                  <p className="text-muted-foreground text-sm">Search intent: {liveOpen.search_intent}</p>
                </DrawerSection>
                {liveOpen.differentiation && (
                  <DrawerSection title="Differentiation">
                    <p className="text-sm">{liveOpen.differentiation}</p>
                  </DrawerSection>
                )}
                {Array.isArray(liveOpen.outline.structure) && liveOpen.outline.structure.length > 0 && (
                  <DrawerSection title="Outline">
                    <ol className="list-inside list-decimal text-sm">
                      {liveOpen.outline.structure.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                    {typeof liveOpen.outline.notes === "string" && liveOpen.outline.notes && (
                      <p className="text-muted-foreground mt-1 text-sm">{liveOpen.outline.notes}</p>
                    )}
                  </DrawerSection>
                )}
                {liveOpen.information_requirements.length > 0 && (
                  <DrawerSection title="Information you must supply">
                    <ul className="list-inside list-disc text-sm">
                      {liveOpen.information_requirements.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </DrawerSection>
                )}
                {Object.keys(liveOpen.evidence_requirements).length > 0 && (
                  <DrawerSection title="Evidence requirements">
                    <EvidenceList evidence={liveOpen.evidence_requirements} />
                  </DrawerSection>
                )}
                {liveOpen.entity_requirements.length > 0 && (
                  <DrawerSection title="Entity requirements">
                    <ul className="list-inside list-disc text-sm">
                      {liveOpen.entity_requirements.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </DrawerSection>
                )}
                {liveOpen.citation_opportunities.length > 0 && (
                  <DrawerSection title="Citation opportunities">
                    <div className="flex flex-col gap-2">
                      {liveOpen.citation_opportunities.map((c, i) => (
                        <EvidenceList key={i} evidence={c} />
                      ))}
                    </div>
                  </DrawerSection>
                )}
                <p className="text-muted-foreground text-xs">
                  Source: {liveOpen.source_key} · created {fmtDateTime(liveOpen.created_at)}
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
