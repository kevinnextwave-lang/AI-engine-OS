"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { AgentWorkflow, AgentWorkflowListResponse } from "@ai-search-growth-os/types";
import {
  Badge,
  Button,
  Input,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ai-search-growth-os/ui";
import { CheckIcon, CircleIcon, Loader2Icon, XIcon } from "lucide-react";

const ACTIVE = new Set(["queued", "running", "awaiting_approval", "paused"]);

function StepIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckIcon className="size-4 text-emerald-600" aria-hidden="true" />;
  if (status === "running") return <Loader2Icon className="size-4 animate-spin text-amber-600" aria-hidden="true" />;
  if (status === "failed" || status === "cancelled") return <XIcon className="text-destructive size-4" aria-hidden="true" />;
  return <CircleIcon className="text-muted-foreground size-4" aria-hidden="true" />;
}

function WorkflowDrawer({
  workflowId,
  onClose,
  onChanged,
}: {
  workflowId: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  return (
    <Sheet open={workflowId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        {workflowId && <WorkflowDrawerBody key={workflowId} workflowId={workflowId} onChanged={onChanged} />}
      </SheetContent>
    </Sheet>
  );
}

function WorkflowDrawerBody({ workflowId, onChanged }: { workflowId: string; onChanged: () => void }) {
  const [wf, setWf] = React.useState<AgentWorkflow | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    api.agentWorkflows
      .get(workflowId)
      .then((w) => {
        setWf(w);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load workflow"));
  }, [workflowId]);

  React.useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          {wf ? label(wf.workflow_type) : "Workflow"}
          {wf && <StatusBadge value={wf.status} />}
        </SheetTitle>
        <SheetDescription>{wf?.objective}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-4 pb-6">
              {error && <p className="text-destructive text-sm">{error}</p>}
              {!wf && !error && <Skeleton className="h-40 w-full" />}
              {wf && (
                <>
                  {wf.hold_reason && (
                    <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                      {wf.hold_reason}
                      {wf.status === "awaiting_approval" && (
                        <span className="text-muted-foreground block pt-1 text-xs">
                          Decide the pending actions under Runs &amp; Approvals, then resume.
                        </span>
                      )}
                    </p>
                  )}
                  {wf.error_message && <p className="text-destructive text-sm">{wf.error_message}</p>}
                  <div className="flex gap-2">
                    {(wf.status === "queued" || wf.status === "running") && (
                      <Button size="sm" variant="outline" onClick={() => void act(() => api.agentWorkflows.pause(wf.id))} disabled={busy}>
                        Pause
                      </Button>
                    )}
                    {(wf.status === "paused" || wf.status === "awaiting_approval") && (
                      <Button size="sm" onClick={() => void act(() => api.agentWorkflows.resume(wf.id))} disabled={busy}>
                        Resume
                      </Button>
                    )}
                    {ACTIVE.has(wf.status) && (
                      <Button size="sm" variant="ghost" onClick={() => void act(() => api.agentWorkflows.cancel(wf.id))} disabled={busy}>
                        Cancel
                      </Button>
                    )}
                  </div>
                  <DrawerSection title="Steps">
                    <ol className="flex flex-col gap-2">
                      {wf.steps.map((s) => (
                        <li key={s.id} className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
                          <StepIcon status={s.status} />
                          <span className="font-medium">{label(s.agent_name)}</span>
                          <StatusBadge value={s.status} className="ml-auto" />
                        </li>
                      ))}
                    </ol>
                  </DrawerSection>
                  {wf.action_plan && wf.action_plan.length > 0 && (
                    <>
                      <Separator />
                      <DrawerSection title={`Consolidated action plan (${wf.action_plan.length})`}>
                        <div className="rounded-lg border">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-10">#</TableHead>
                                <TableHead>Action</TableHead>
                                <TableHead>Impact area</TableHead>
                                <TableHead>Effort</TableHead>
                                <TableHead>Approval</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {wf.action_plan.map((item) => (
                                <TableRow key={item.priority}>
                                  <TableCell className="tabular-nums">{item.priority}</TableCell>
                                  <TableCell className="max-w-sm">
                                    <p className="text-sm">{item.action}</p>
                                    <p className="text-muted-foreground text-xs">{item.reason}</p>
                                    <details className="mt-1">
                                      <summary className="text-muted-foreground cursor-pointer text-xs">Evidence · {label(item.agent)} (step {item.step})</summary>
                                      <div className="mt-1.5">
                                        <EvidenceList evidence={item.evidence} />
                                      </div>
                                    </details>
                                  </TableCell>
                                  <TableCell className="text-sm">{item.expected_impact_area}</TableCell>
                                  <TableCell>
                                    <Badge variant="outline">{item.effort}</Badge>
                                  </TableCell>
                                  <TableCell>
                                    <StatusBadge value={item.approval_status} />
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      </DrawerSection>
                    </>
                  )}
                </>
              )}
      </div>
    </>
  );
}

export default function AgentWorkflowsPage() {
  const res = useProjectResource<AgentWorkflowListResponse>(
    React.useCallback((pid) => api.agentWorkflows.list(pid, { limit: 50 }), []),
    { pollMs: 5000, isActive: (d) => d.items.some((w) => ACTIVE.has(w.status)) },
  );
  const [objective, setObjective] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const d = res.data;

  const start = async () => {
    if (!res.projectId) return;
    setBusy(true);
    setNotice(null);
    try {
      const wf = await api.agentWorkflows.create(
        res.projectId,
        objective.trim() || "Full AI-visibility optimization pass",
      );
      setObjective("");
      setOpenId(wf.id);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not start the workflow");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionFrame
      title="Agent Workflows"
      description="The full optimization chain — research → content strategy → content optimization → entity optimization — run as one workflow. It pauses for your approval whenever a step proposes changes and ends with one consolidated, prioritised action plan."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
    >
      <Toolbar>
        <Input
          aria-label="Workflow objective"
          placeholder="Objective, e.g. “Improve visibility for bottom-funnel prompts”"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          className="max-w-xl flex-1"
        />
        <Button onClick={() => void start()} disabled={!res.projectId || busy}>
          {busy ? "Starting…" : "Start full optimization"}
        </Button>
      </Toolbar>
      {notice && <p className="text-destructive mb-3 text-sm">{notice}</p>}
      <DataTable
        head={["Workflow", "Objective", "Progress", "Status", "Created"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No workflows yet — start the full optimization chain above." : null}
      >
        {(d?.items ?? []).map((w) => (
          <TableRow key={w.id} className="cursor-pointer" onClick={() => setOpenId(w.id)}>
            <TableCell className="font-medium">{label(w.workflow_type)}</TableCell>
            <TableCell className="text-muted-foreground max-w-md truncate" title={w.objective}>
              {w.objective}
            </TableCell>
            <TableCell className="tabular-nums">
              {w.steps_completed}/{w.steps_total} steps
            </TableCell>
            <TableCell>
              <StatusBadge value={w.status} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(w.created_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <WorkflowDrawer workflowId={openId} onClose={() => setOpenId(null)} onChanged={res.refresh} />
    </SectionFrame>
  );
}
