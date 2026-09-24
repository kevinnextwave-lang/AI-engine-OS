"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { CompetitiveAlert, CompetitiveAlertListResponse, CompetitiveAlertType } from "@ai-search-growth-os/types";
import {
  Badge,
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

const ALERT_TYPES: CompetitiveAlertType[] = [
  "competitor_overtakes_brand",
  "visibility_drop",
  "competitor_visibility_jump",
  "new_competitor",
  "new_citation_source",
  "citation_gap_increase",
  "new_competitor_claim",
  "content_gap",
];

export default function CompetitiveAlertsPage() {
  const [alertType, setAlertType] = React.useState("");
  const [severity, setSeverity] = React.useState("");
  const [status, setStatus] = React.useState("");
  const res = useProjectResource<CompetitiveAlertListResponse>(
    React.useCallback(
      (pid) =>
        api.competitiveAlerts.list(pid, {
          alert_type: alertType || undefined,
          severity: severity || undefined,
          status: status || undefined,
          limit: 100,
        }),
      [alertType, severity, status],
    ),
  );
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<CompetitiveAlert | null>(null);
  const d = res.data;
  const liveOpen = open ? (d?.items.find((a) => a.id === open.id) ?? open) : null;

  const detect = async () => {
    if (!res.projectId) return;
    setBusy("detect");
    setNotice(null);
    try {
      const r = await api.competitiveAlerts.detect(res.projectId);
      setNotice(`Compared ${r.current_responses} vs ${r.previous_responses} responses — ${r.alerts_created} new alerts.`);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Detection failed");
    } finally {
      setBusy(null);
    }
  };

  const setAlertStatus = async (alert: CompetitiveAlert, next: "new" | "read" | "dismissed") => {
    setBusy(alert.id);
    try {
      await api.competitiveAlerts.setStatus(alert.id, next);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionFrame
      title="Competitive Alerts"
      description="Meaningful changes in your competitive AI landscape, detected by comparing this period's measured data with the previous period. Every alert shows the before/after evidence it was raised from."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <Button onClick={() => void detect()} disabled={!res.projectId || busy !== null}>
          {busy === "detect" ? "Detecting…" : "Run detection"}
        </Button>
      }
    >
      <Toolbar>
        <NativeSelect aria-label="Alert type" value={alertType} onChange={(e) => setAlertType(e.target.value)} className="w-56">
          <option value="">All alert types</option>
          {ALERT_TYPES.map((t) => (
            <option key={t} value={t}>
              {label(t)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-36">
          <option value="">Any severity</option>
          {["critical", "high", "medium", "low"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-36">
          <option value="">Any status</option>
          {["new", "read", "dismissed"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        <span className="text-muted-foreground ml-auto text-xs">
          {d ? `${d.unread} unread` : ""}
          {d?.detected_at ? ` · last detection ${fmtDateTime(d.detected_at)}` : ""}
        </span>
      </Toolbar>
      {notice && <p className="text-muted-foreground mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Alert", "Type", "Severity", "Status", "Detected", ""]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No alerts for the current filters. Run detection after new responses come in." : null}
      >
        {(d?.items ?? []).map((a) => (
          <TableRow key={a.id} className={`cursor-pointer ${a.status === "new" ? "font-medium" : ""}`} onClick={() => setOpen(a)}>
            <TableCell className="max-w-lg">
              <p>{a.title}</p>
              <p className="text-muted-foreground truncate text-sm font-normal" title={a.description}>
                {a.description}
              </p>
            </TableCell>
            <TableCell className="text-sm">{label(a.alert_type)}</TableCell>
            <TableCell>
              <StatusBadge value={a.severity} />
            </TableCell>
            <TableCell>
              <StatusBadge value={a.status} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(a.detected_at)}</TableCell>
            <TableCell onClick={(e) => e.stopPropagation()}>
              <div className="flex gap-1.5">
                {a.status === "new" && (
                  <Button size="sm" variant="outline" onClick={() => void setAlertStatus(a, "read")} disabled={busy !== null}>
                    Mark read
                  </Button>
                )}
                {a.status !== "dismissed" && (
                  <Button size="sm" variant="ghost" onClick={() => void setAlertStatus(a, "dismissed")} disabled={busy !== null}>
                    Dismiss
                  </Button>
                )}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </DataTable>
      <Sheet open={liveOpen !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {liveOpen && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  {liveOpen.title}
                  <Badge variant={liveOpen.severity === "critical" ? "critical" : liveOpen.severity === "high" ? "high" : "medium"}>
                    {liveOpen.severity}
                  </Badge>
                </SheetTitle>
                <SheetDescription>
                  {label(liveOpen.alert_type)} · detected {fmtDateTime(liveOpen.detected_at)}
                </SheetDescription>
              </SheetHeader>
              <div className="flex flex-col gap-5 px-4 pb-6">
                <DrawerSection title="What changed">
                  <p className="text-sm">{liveOpen.description}</p>
                </DrawerSection>
                <DrawerSection title="Evidence">
                  <EvidenceList evidence={liveOpen.evidence} />
                </DrawerSection>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </SectionFrame>
  );
}
