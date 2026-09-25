"use client";

import { EmptyAction } from "@/components/empty-action";
import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type {
  ContentOptimizationReview,
  ContentReviewListResponse,
  ContentReviewStatus,
  ProposedContentChange,
} from "@ai-search-growth-os/types";
import {
  Button,
  NativeSelect,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  TableCell,
  TableRow,
} from "@ai-search-growth-os/ui";

function ChangeCard({
  change,
  busy,
  onDecide,
}: {
  change: ProposedContentChange;
  busy: boolean;
  onDecide: (changeId: string, action: "accept" | "edit" | "reject", text?: string) => Promise<void>;
}) {
  const [editing, setEditing] = React.useState(false);
  const [text, setText] = React.useState(change.proposed_text);
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="text-muted-foreground text-xs">{change.location}</p>
        <span className="flex shrink-0 gap-1.5">
          <StatusBadge value={change.confidence} />
          <StatusBadge value={change.decision} />
        </span>
      </div>
      <div className="mt-2 grid gap-2">
        <div className="rounded-md border-destructive/25 bg-destructive/5 border p-2">
          <p className="text-muted-foreground mb-0.5 text-xs">Current</p>
          <p className="whitespace-pre-wrap">{change.current_text}</p>
        </div>
        <div className="rounded-md border-success/25 bg-success/5 border p-2">
          <p className="text-muted-foreground mb-0.5 text-xs">Proposed</p>
          <p className="whitespace-pre-wrap">{change.decided_text ?? change.proposed_text}</p>
        </div>
      </div>
      <p className="text-muted-foreground mt-2 text-xs">{change.reason}</p>
      {Object.keys(change.evidence).length > 0 && (
        <details className="mt-1.5">
          <summary className="text-muted-foreground cursor-pointer text-xs">Evidence</summary>
          <div className="mt-1.5">
            <EvidenceList evidence={change.evidence} />
          </div>
        </details>
      )}
      {change.decision === "pending" && !editing && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={() => void onDecide(change.change_id, "accept")} disabled={busy}>
            Accept
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(true)} disabled={busy}>
            Edit
          </Button>
          <Button size="sm" variant="outline" onClick={() => void onDecide(change.change_id, "reject")} disabled={busy}>
            Reject
          </Button>
        </div>
      )}
      {editing && (
        <div className="mt-3 flex flex-col gap-2">
          <textarea
            aria-label="Edited text"
            className="border-input bg-background min-h-24 w-full rounded-md border p-2 text-sm"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                // Close the editor only after the decision persisted, so a
                // failure keeps the edited text on screen.
                void onDecide(change.change_id, "edit", text).then(() => setEditing(false));
              }}
              disabled={busy || !text.trim()}
            >
              Save edited version
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewDrawer({ reviewId, onClose, onChanged }: { reviewId: string | null; onClose: () => void; onChanged: () => void }) {
  return (
    <Sheet open={reviewId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        {reviewId && <ReviewDrawerBody key={reviewId} reviewId={reviewId} onChanged={onChanged} />}
      </SheetContent>
    </Sheet>
  );
}

function ReviewDrawerBody({ reviewId, onChanged }: { reviewId: string; onChanged: () => void }) {
  const [review, setReview] = React.useState<ContentOptimizationReview | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    api.contentReviews
      .get(reviewId)
      .then((r) => {
        setReview(r);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load review"));
  }, [reviewId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const decide = async (changeId: string, action: "accept" | "edit" | "reject", text?: string) => {
    setBusy(true);
    try {
      const updated = await api.contentReviews.decideChange(reviewId, changeId, { action, text });
      setReview(updated);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  };

  const pending = review?.proposed_changes.filter((c) => c.decision === "pending").length ?? 0;

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          Content review
          {review && <StatusBadge value={review.status} />}
        </SheetTitle>
        <SheetDescription>
          {review
            ? `Score ${review.score}/100 · ${review.proposed_changes.length} proposed changes (${pending} pending) · analysed ${fmtDateTime(review.analyzed_at)}`
            : ""}
        </SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-4 pb-6">
        {error && <p className="text-destructive text-sm">{error}</p>}
        {!review && !error && <Skeleton className="h-40 w-full" />}
        {review && (
          <>
            <p className="text-muted-foreground text-xs">
              The original page is never modified automatically — accepted and edited texts are recorded here for you to apply.
            </p>
            {review.proposed_changes.length > 0 && (
              <DrawerSection title="Proposed changes">
                <div className="flex flex-col gap-2">
                  {review.proposed_changes.map((c) => (
                    <ChangeCard key={c.change_id} change={c} busy={busy} onDecide={decide} />
                  ))}
                </div>
              </DrawerSection>
            )}
            {review.findings.length > 0 && (
              <DrawerSection title="Findings">
                <div className="flex flex-col gap-2">
                  {review.findings.map((f, i) => (
                    <EvidenceList key={i} evidence={f} />
                  ))}
                </div>
              </DrawerSection>
            )}
          </>
        )}
      </div>
    </>
  );
}

export default function ContentReviewsPage() {
  const [status, setStatus] = React.useState("");
  const res = useProjectResource<ContentReviewListResponse>(
    React.useCallback(
      (pid) => api.contentReviews.list(pid, { status: status || undefined, limit: 100 }),
      [status],
    ),
  );
  const [openId, setOpenId] = React.useState<string | null>(null);
  const d = res.data;

  return (
    <SectionFrame
      title="Content Reviews"
      description="Page-by-page GEO reviews from the Content Optimization agent, each with concrete text changes to accept, edit or reject. No change ever touches the live page — you stay in control of what gets applied."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
    >
      <Toolbar>
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
          <option value="">Any status</option>
          {(["draft", "reviewing", "completed", "archived"] as ContentReviewStatus[]).map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </NativeSelect>
      </Toolbar>
      <DataTable
        head={["Page", "Score", "Changes", "Pending", "Confidence", "Status", "Analyzed"]}
        loading={res.loading}
        empty={
          d && d.items.length === 0
            ? {
                title: "No content reviews yet",
                description:
                  "This queue holds page-level rewrite proposals from the Content Optimization agent, for you to approve, edit or reject. It's empty because the agent hasn't been run on this project's crawled pages yet.",
                action: <EmptyAction href="/app/agents">Run the Content Optimization agent</EmptyAction>,
              }
            : null
        }
      >
        {(d?.items ?? []).map((r) => (
          <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpenId(r.id)}>
            <TableCell className="max-w-md truncate font-medium" title={r.page_url ?? r.page_id}>
              {r.page_url ?? r.page_id}
            </TableCell>
            <TableCell className="tabular-nums">{r.score}</TableCell>
            <TableCell className="tabular-nums">{r.changes_count}</TableCell>
            <TableCell className="tabular-nums">{r.pending_changes}</TableCell>
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
      <ReviewDrawer reviewId={openId} onClose={() => setOpenId(null)} onChanged={res.refresh} />
    </SectionFrame>
  );
}
