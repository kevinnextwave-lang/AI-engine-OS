"use client";

import * as React from "react";
import Link from "next/link";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { NotificationChannelsSheet } from "@/components/section/notification-channels";
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


/** Where each alert type is investigated — existing surfaces only. */
const ALERT_DESTINATION: Partial<Record<CompetitiveAlertType, { href: string; label: string; hint: string }>> = {
  competitor_overtakes_brand: { href: "/app/ai-visibility/competitors", label: "Review competitor comparison", hint: "Opens the measured mention shares and the evidence behind them." },
  competitor_visibility_jump: { href: "/app/ai-visibility/competitors", label: "Review competitor comparison", hint: "Opens the measured mention shares and the evidence behind them." },
  new_competitor: { href: "/app/competitive/discovery", label: "Review competitor candidates", hint: "Confirm or reject what discovery found." },
  visibility_drop: { href: "/app/ai-visibility/trends", label: "Review visibility trend", hint: "See when the drop happened and at what confidence." },
  new_citation_source: { href: "/app/ai-intelligence/sources", label: "Review cited sources", hint: "Opens the source profiles behind recent answers." },
  citation_gap_increase: { href: "/app/ai-intelligence/citation-gaps", label: "Review citation gaps", hint: "The sources citing competitors but not you." },
  new_competitor_claim: { href: "/app/ai-intelligence/claims", label: "Review competitor claims", hint: "What AI answers assert about competitors." },
  content_gap: { href: "/app/competitive/content-gaps", label: "Review content gaps", hint: "Topics where competitors have coverage you lack." },
};

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
  const [channelsOpen, setChannelsOpen] = React.useState(false);
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
        <>
          <Button variant="outline" onClick={() => setChannelsOpen(true)} disabled={!res.projectId}>
            Notification channels
          </Button>
          <Button onClick={() => void detect()} disabled={!res.projectId || busy !== null}>
            {busy === "detect" ? "Detecting…" : "Run detection"}
          </Button>
        </>
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
        empty={
          d && d.items.length === 0
            ? {
                title: "No alerts",
                description:
                  "Alerts flag measured changes in competitive standing — a competitor overtaking your mention rate, new citation sources, sudden drops. Nothing matches the current filters; detection runs over newly parsed responses, so check back after the next analysis.",
              }
            : null
        }
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
                <Button size="sm" variant="ghost" onClick={() => setOpen(a)}>
                  Details
                </Button>
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
                {/* The ACT step: every alert type routes to the existing
                    surface where this kind of change is investigated. */}
                {ALERT_DESTINATION[liveOpen.alert_type] && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button asChild size="sm">
                      <Link href={ALERT_DESTINATION[liveOpen.alert_type]!.href}>
                        {ALERT_DESTINATION[liveOpen.alert_type]!.label}
                      </Link>
                    </Button>
                    <span className="text-muted-foreground text-xs">
                      {ALERT_DESTINATION[liveOpen.alert_type]!.hint}
                    </span>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <NotificationChannelsSheet
        projectId={res.projectId}
        open={channelsOpen}
        onClose={() => setChannelsOpen(false)}
      />
    </SectionFrame>
  );
}
