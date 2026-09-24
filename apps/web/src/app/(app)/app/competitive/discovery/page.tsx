"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { CompetitorCandidate, CompetitorCandidateListResponse } from "@ai-search-growth-os/types";
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

const SOURCE_LABEL: Record<string, string> = {
  ai_responses: "AI responses",
  website_intelligence: "Website intelligence",
  ai_assisted: "AI assisted",
  combined: "Combined",
};

export default function CompetitorDiscoveryPage() {
  const [status, setStatus] = React.useState("");
  const res = useProjectResource<CompetitorCandidateListResponse>(
    React.useCallback(
      (pid) => api.competitorCandidates.list(pid, { status: status || undefined, limit: 100 }),
      [status],
    ),
  );
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<CompetitorCandidate | null>(null);
  const d = res.data;

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setNotice(null);
    try {
      await fn();
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionFrame
      title="Competitor Discovery"
      description="Companies that keep appearing alongside your brand in AI answers. Candidates never affect your metrics until you accept them as competitors — review the evidence and decide."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <Button
          onClick={() =>
            void act("discover", () => api.competitorCandidates.discover(res.projectId!, {}))
          }
          disabled={!res.projectId || busy !== null}
        >
          {busy === "discover" ? "Scanning…" : "Scan for candidates"}
        </Button>
      }
    >
      <Toolbar>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-36">
          <option value="">All statuses</option>
          {["new", "reviewing", "accepted", "rejected"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        {d?.discovered_at && (
          <span className="text-muted-foreground ml-auto text-xs">Last scan {fmtDateTime(d.discovered_at)}</span>
        )}
      </Toolbar>
      {notice && <p className="text-destructive mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Candidate", "Domain", "Confidence", "Source", "Status", "Reason", ""]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No candidates yet. Run a scan once you have parsed AI responses." : null}
      >
        {(d?.items ?? []).map((c) => (
          <TableRow key={c.id} className="cursor-pointer" onClick={() => setOpen(c)}>
            <TableCell className="font-medium">{c.name}</TableCell>
            <TableCell className="text-muted-foreground">{c.domain ?? "—"}</TableCell>
            <TableCell>
              <StatusBadge value={c.confidence_label} />
              <span className="text-muted-foreground ml-1.5 text-xs tabular-nums">{Math.round(c.confidence * 100)}%</span>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{SOURCE_LABEL[c.source] ?? c.source}</TableCell>
            <TableCell>
              <StatusBadge value={c.status} />
            </TableCell>
            <TableCell className="text-muted-foreground max-w-md truncate text-sm" title={c.reason}>
              {c.reason}
            </TableCell>
            <TableCell onClick={(e) => e.stopPropagation()}>
              {(c.status === "new" || c.status === "reviewing") && (
                <div className="flex gap-1.5">
                  <Button
                    size="sm"
                    onClick={() => void act(c.id + ":a", () => api.competitorCandidates.accept(c.id))}
                    disabled={busy !== null}
                  >
                    {busy === c.id + ":a" ? "…" : "Accept"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void act(c.id + ":r", () => api.competitorCandidates.reject(c.id))}
                    disabled={busy !== null}
                  >
                    {busy === c.id + ":r" ? "…" : "Reject"}
                  </Button>
                </div>
              )}
            </TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>{open.name}</SheetTitle>
                <SheetDescription>
                  {open.domain ?? "no domain"} · discovered {fmtDateTime(open.discovered_at)}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="Why this was surfaced">
                  <p className="text-sm">{open.reason}</p>
                </DrawerSection>
                <DrawerSection title="Evidence">
                  <EvidenceList evidence={open.evidence} />
                </DrawerSection>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
