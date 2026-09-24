"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { AgentAction, AgentRun, AgentRunListResponse } from "@ai-search-growth-os/types";
import {
  Badge,
  Button,
  NativeSelect,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  TableCell,
  TableRow,
} from "@ai-search-growth-os/ui";

const ACTIVE = new Set(["queued", "running"]);

interface Finding {
  title?: string;
  priority?: number;
  confidence?: string;
  statements?: Record<string, string>;
  evidence?: Record<string, unknown>;
  [k: string]: unknown;
}

function FindingCard({ finding }: { finding: Finding }) {
  const statements = finding.statements ?? {};
  return (
    <div className="rounded-lg border p-3 text-sm">
      <p className="flex items-start justify-between gap-2 font-medium">
        {finding.title ?? "Finding"}
        <span className="flex shrink-0 gap-1.5">
          {finding.confidence && <StatusBadge value={String(finding.confidence)} />}
          {typeof finding.priority === "number" && (
            <Badge variant="outline" className="tabular-nums">P{finding.priority}</Badge>
          )}
        </span>
      </p>
      {Object.entries(statements).map(([kind, text]) => (
        <p key={kind} className="mt-1.5">
          <span className="text-muted-foreground capitalize">{kind}: </span>
          {text}
        </p>
      ))}
      {finding.evidence && Object.keys(finding.evidence).length > 0 && (
        <details className="mt-2">
          <summary className="text-muted-foreground cursor-pointer text-xs">Evidence</summary>
          <div className="mt-1.5">
            <EvidenceList evidence={finding.evidence} />
          </div>
        </details>
      )}
    </div>
  );
}

function ActionRow({
  action,
  busy,
  onDecide,
}: {
  action: AgentAction;
  busy: boolean;
  onDecide: (id: string, decision: "approve" | "reject") => void;
}) {
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium">{action.description}</p>
        <span className="flex shrink-0 gap-1.5">
          <Badge variant={action.risk_level === "high" ? "critical" : action.risk_level === "medium" ? "high" : "low"}>
            {action.risk_level} risk
          </Badge>
          <StatusBadge value={action.status} />
        </span>
      </div>
      <p className="text-muted-foreground mt-1 text-xs">{label(action.action_type)}</p>
      {Object.keys(action.payload).length > 0 && (
        <details className="mt-2">
          <summary className="text-muted-foreground cursor-pointer text-xs">Payload</summary>
          <div className="mt-1.5">
            <EvidenceList evidence={action.payload} />
          </div>
        </details>
      )}
      {action.status === "pending" && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={() => onDecide(action.id, "approve")} disabled={busy}>
            Approve
          </Button>
          <Button size="sm" variant="outline" onClick={() => onDecide(action.id, "reject")} disabled={busy}>
            Reject
          </Button>
        </div>
      )}
      {action.approved_at && (
        <p className="text-muted-foreground mt-2 text-xs">Decided {fmtDateTime(action.approved_at)}</p>
      )}
    </div>
  );
}

function RunDrawer({ runId, onClose, onChanged }: { runId: string | null; onClose: () => void; onChanged: () => void }) {
  return (
    <Sheet open={runId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        {runId && <RunDrawerBody key={runId} runId={runId} onChanged={onChanged} />}
      </SheetContent>
    </Sheet>
  );
}

function RunDrawerBody({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const [run, setRun] = React.useState<AgentRun | null>(null);
  const [actions, setActions] = React.useState<AgentAction[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    Promise.all([api.agents.getRun(runId), api.agents.actions(runId)])
      .then(([r, a]) => {
        setRun(r);
        setActions(a);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load run"));
  }, [runId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const decide = async (actionId: string, decision: "approve" | "reject") => {
    setBusy(true);
    try {
      await (decision === "approve" ? api.agents.approveAction(actionId) : api.agents.rejectAction(actionId));
      load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!run) return;
    setBusy(true);
    try {
      await api.agents.cancelRun(run.id);
      load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setBusy(false);
    }
  };

  const result = (run?.result ?? {}) as {
    summary?: string;
    findings?: Finding[];
    warnings?: string[];
    confidence?: string | null;
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          {run ? label(run.agent_name) : "Agent run"}
          {run && <StatusBadge value={run.status} />}
        </SheetTitle>
        <SheetDescription>{run?.objective}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-4 pb-6">
              {error && <p className="text-destructive text-sm">{error}</p>}
              {!run && !error && <Skeleton className="h-40 w-full" />}
              {run && (
                <>
                  <p className="text-muted-foreground text-xs">
                    Started {run.started_at ? fmtDateTime(run.started_at) : "—"} ·{" "}
                    {run.execution_time_ms != null ? `${(run.execution_time_ms / 1000).toFixed(1)}s` : "…"} ·{" "}
                    {run.input_tokens != null ? `${run.input_tokens}/${run.output_tokens} tokens` : "no LLM calls"}
                    {run.estimated_cost != null && ` · est. $${run.estimated_cost}`}
                  </p>
                  {ACTIVE.has(run.status) && (
                    <Button size="sm" variant="outline" onClick={() => void cancel()} disabled={busy} className="self-start">
                      Cancel run
                    </Button>
                  )}
                  {run.error_message && <p className="text-destructive text-sm">{run.error_message}</p>}
                  {result.summary && (
                    <DrawerSection title="Summary">
                      <p className="text-sm whitespace-pre-wrap">{result.summary}</p>
                    </DrawerSection>
                  )}
                  {result.warnings && result.warnings.length > 0 && (
                    <DrawerSection title="Warnings">
                      <ul className="text-muted-foreground list-inside list-disc text-sm">
                        {result.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </DrawerSection>
                  )}
                  {result.findings && result.findings.length > 0 && (
                    <DrawerSection title={`Findings (${result.findings.length})`}>
                      <div className="flex flex-col gap-2">
                        {result.findings.map((f, i) => (
                          <FindingCard key={i} finding={f} />
                        ))}
                      </div>
                    </DrawerSection>
                  )}
                  {actions && actions.length > 0 && (
                    <>
                      <Separator />
                      <DrawerSection title={`Proposed actions (${actions.length})`}>
                        <p className="text-muted-foreground mb-1 text-xs">
                          Nothing executes without your approval; medium and high risk actions always require it.
                        </p>
                        <div className="flex flex-col gap-2">
                          {actions.map((a) => (
                            <ActionRow key={a.id} action={a} busy={busy} onDecide={(id, dec) => void decide(id, dec)} />
                          ))}
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

export default function AgentRunsPage() {
  const [status, setStatus] = React.useState("");
  const [agent, setAgent] = React.useState("");
  const res = useProjectResource<AgentRunListResponse>(
    React.useCallback(
      (pid) =>
        api.agents.runs(pid, { status: status || undefined, agent_name: agent || undefined, limit: 50 }),
      [status, agent],
    ),
    { pollMs: 4000, isActive: (d) => d.items.some((r) => ACTIVE.has(r.status)) },
  );
  const [openId, setOpenId] = React.useState<string | null>(null);
  const d = res.data;

  return (
    <SectionFrame
      title="Runs & Approvals"
      description="Every agent run with its findings and proposed actions. Runs stop in “awaiting approval” whenever an agent proposes changes — decide each action to complete them."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
    >
      <Toolbar>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
          <option value="">Any status</option>
          {["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"].map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label="Agent" value={agent} onChange={(e) => setAgent(e.target.value)} className="w-52">
          <option value="">All agents</option>
          {["research", "content-strategy", "content-optimization", "entity-optimization"].map((a) => (
            <option key={a} value={a}>
              {label(a)}
            </option>
          ))}
        </NativeSelect>
      </Toolbar>
      <DataTable
        head={["Agent", "Objective", "Status", "Duration", "Created"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No agent runs yet — start one from the Run Agents page." : null}
      >
        {(d?.items ?? []).map((r) => (
          <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpenId(r.id)}>
            <TableCell className="font-medium">{label(r.agent_name)}</TableCell>
            <TableCell className="text-muted-foreground max-w-md truncate" title={r.objective}>
              {r.objective}
            </TableCell>
            <TableCell>
              <StatusBadge value={r.status} />
            </TableCell>
            <TableCell className="tabular-nums">
              {r.execution_time_ms != null ? `${(r.execution_time_ms / 1000).toFixed(1)}s` : "—"}
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">{fmtDateTime(r.created_at)}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      <RunDrawer runId={openId} onClose={() => setOpenId(null)} onChanged={res.refresh} />
    </SectionFrame>
  );
}
