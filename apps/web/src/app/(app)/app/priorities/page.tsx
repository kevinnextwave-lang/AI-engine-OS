"use client";

import { ArrowRightIcon, ListTodoIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/geo/empty-state";
import { StatusBadge } from "@/components/section/primitives";
import { EvidenceList } from "@/components/section/evidence";
import { SectionFrame } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { SectionHeader } from "@/components/shell/section-header";
import { relativeTime } from "@/lib/format";
import { api } from "@/lib/api";
import {
  ALERT_DESTINATION,
  ALERT_SEVERITY_ORDER,
  coveredGapIds,
  latestResearchRun,
  priorityFindings,
  type PriorityFinding,
} from "@/lib/priorities";
import type { AgentRunListResponse, CompetitiveAlertListResponse, ContentGapListResponse } from "@ai-search-growth-os/types";
import { Badge, Button, Skeleton } from "@ai-search-growth-os/ui";

const TOP_COUNT = 5;

/**
 * The PRIORITIZE surface: one place that answers "what should I work on
 * now?" from data the product has already measured and stored.
 *
 * - Top priorities = the latest Research Agent run's findings, in the run's
 *   own stored order (priority_score, computed server-side). Each links to
 *   the ACT surface its backend-declared impact area maps to.
 * - Content gaps and new alerts are adjacent queues with their own existing
 *   ordering (opportunity score / severity). They are deliberately NOT
 *   merged into the findings ranking — the scores aren't comparable, and a
 *   fused ranking would be invented precision.
 */
export default function PrioritiesPage() {
  const runs = useProjectResource<AgentRunListResponse>(
    React.useCallback((pid) => api.agents.runs(pid, { agent_name: "research", limit: 10 }), []),
  );
  const gaps = useProjectResource<ContentGapListResponse>(
    React.useCallback((pid) => api.contentGaps.list(pid, { status: "new", limit: 10 }), []),
  );
  const alerts = useProjectResource<CompetitiveAlertListResponse>(
    React.useCallback((pid) => api.competitiveAlerts.list(pid, { status: "new", limit: 10 }), []),
  );

  const [showAll, setShowAll] = React.useState(false);
  const run = runs.data ? latestResearchRun(runs.data.items) : null;
  const findings = React.useMemo(() => (run ? priorityFindings(run) : []), [run]);
  const shown = showAll ? findings : findings.slice(0, TOP_COUNT);

  // Dedup by canonical id: a gap already represented by a research finding
  // above is not repeated in this queue (research stores content_gap_id in
  // the finding's evidence — no heuristic matching).
  const topGaps = React.useMemo(() => {
    const covered = coveredGapIds(findings);
    return [...(gaps.data?.items ?? [])]
      .filter((g) => !covered.has(g.id))
      .sort((a, b) => b.opportunity_score - a.opportunity_score)
      .slice(0, 3);
  }, [gaps.data, findings]);
  const topAlerts = React.useMemo(
    () =>
      [...(alerts.data?.items ?? [])]
        .sort((a, b) => (ALERT_SEVERITY_ORDER[a.severity] ?? 9) - (ALERT_SEVERITY_ORDER[b.severity] ?? 9))
        .slice(0, 3),
    [alerts.data],
  );

  const loading = runs.data === null && runs.error === null;
  const allEmpty = !loading && findings.length === 0 && topGaps.length === 0 && topAlerts.length === 0 && gaps.data !== null && alerts.data !== null;

  return (
    <SectionFrame
      title="Priorities"
      description="What to work on now, from what the product has measured: the latest research findings in their stored priority order, plus the open content gaps and new alerts waiting for review."
      projectId={runs.projectId}
      projectLoading={runs.projectLoading}
      error={runs.error}
      onRetry={() => {
        runs.refresh();
        gaps.refresh();
        alerts.refresh();
      }}
    >
      {loading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : allEmpty ? (
        <EmptyState
          icon={ListTodoIcon}
          title="No priority actions right now"
          description="Priorities are built from stored research findings, open content gaps and new alerts — none exist for this project yet. Run the Research Agent to analyze your measured data and produce prioritized findings."
        >
          <Button asChild>
            <Link href="/app/agents?agent=research">Run the Research Agent</Link>
          </Button>
        </EmptyState>
      ) : (
        <>
          <section aria-label="Top priorities" className="mb-8">
            <SectionHeader
              title="Top priorities"
              hint={
                run
                  ? `From the Research Agent run ${relativeTime(run.completed_at ?? run.created_at, "")} — its stored priority order, nothing re-ranked.`
                  : "The Research Agent produces ranked findings from your measured data."
              }
              href="/app/agents/runs"
              linkLabel="Open run"
            />
            {findings.length === 0 ? (
              <div className="rounded-xl border border-dashed p-5 text-sm">
                <p className="font-medium">No research findings yet</p>
                <p className="text-muted-foreground mt-1">
                  Run the Research Agent to turn this project&apos;s measured data into ranked, evidence-backed priorities.
                </p>
                <Button asChild size="sm" className="mt-3">
                  <Link href="/app/agents?agent=research">Run the Research Agent</Link>
                </Button>
              </div>
            ) : (
              <ol className="flex flex-col gap-2">
                {shown.map((f, i) => (
                  <PriorityRow key={`${f.runId}:${f.index}`} rank={i + 1} finding={f} />
                ))}
              </ol>
            )}
            {findings.length > TOP_COUNT && (
              <Button size="sm" variant="ghost" className="mt-2" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show top 5 only" : `View all ${findings.length} priorities`}
              </Button>
            )}
          </section>

          {topGaps.length > 0 && (
            <section aria-label="Open content gaps" className="mb-8">
              <SectionHeader
                title="Open content gaps"
                hint={`Highest measured opportunity first${gaps.data ? ` · ${gaps.data.total} new` : ""}.`}
                href="/app/competitive/content-gaps"
                linkLabel="All content gaps"
              />
              <ul className="flex flex-col gap-2">
                {topGaps.map((g) => (
                  <li key={g.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border p-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{g.topic}</p>
                      <p className="text-muted-foreground mt-0.5 text-xs">
                        Opportunity {Math.round(g.opportunity_score)}/100 · {g.confidence} confidence · analyzed{" "}
                        {relativeTime(g.analyzed_at, "–")}
                      </p>
                    </div>
                    <Button asChild size="sm" variant="outline">
                      <Link
                        href={`/app/agents?agent=content-strategy&objective=${encodeURIComponent(
                          `Draft a content brief for “${g.topic}” — opportunity score ${Math.round(g.opportunity_score)}/100 (${g.confidence} confidence).`,
                        )}`}
                      >
                        Draft a brief
                      </Link>
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {topAlerts.length > 0 && (
            <section aria-label="New alerts" className="mb-4">
              <SectionHeader
                title="New alerts"
                hint={`Most severe first${alerts.data ? ` · ${alerts.data.total} unreviewed` : ""}.`}
                href="/app/competitive/alerts"
                linkLabel="All alerts"
              />
              <ul className="flex flex-col gap-2">
                {topAlerts.map((a) => {
                  const dest = ALERT_DESTINATION[a.alert_type];
                  return (
                    <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border p-3 text-sm">
                      <StatusBadge value={a.severity} />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{a.title}</p>
                        <p className="text-muted-foreground mt-0.5 text-xs">Detected {relativeTime(a.detected_at, "–")}</p>
                      </div>
                      {dest && (
                        <Button asChild size="sm" variant="outline">
                          <Link href={dest.href}>{dest.label}</Link>
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}
    </SectionFrame>
  );
}

/** One compact, scannable priority: what → why → evidence → act. */
function PriorityRow({ rank, finding: f }: { rank: number; finding: PriorityFinding }) {
  return (
    <li className="rounded-xl border p-4">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <span aria-hidden="true" className="text-muted-foreground w-5 shrink-0 pt-0.5 text-right text-sm font-semibold tabular-nums">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            {f.title}
            {f.impact && <StatusBadge value={f.impact} />}
            {f.confidence && <span className="text-muted-foreground text-xs font-normal">{f.confidence} confidence</span>}
            {f.area && (
              <Badge variant="outline" className="font-normal">
                {f.area}
              </Badge>
            )}
          </p>
          {f.observed && <p className="mt-1 text-sm">{f.observed}</p>}
          {f.whyNow && <p className="text-muted-foreground mt-1 text-xs">{f.whyNow}</p>}
          {Object.keys(f.evidence).length > 0 && (
            <details className="mt-2">
              <summary className="text-muted-foreground cursor-pointer text-xs">Evidence</summary>
              <div className="mt-1.5">
                <EvidenceList evidence={f.evidence} />
              </div>
            </details>
          )}
        </div>
        {f.action && (
          <Button asChild size="sm" className="shrink-0">
            <Link href={f.action.href}>
              {f.action.label}
              <ArrowRightIcon aria-hidden="true" />
            </Link>
          </Button>
        )}
      </div>
    </li>
  );
}
