"use client";

import { CheckCircle2Icon, RotateCcwIcon, TimerIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { fmtDateFull, relativeTime } from "@/lib/format";
import type { VerificationSummary } from "@/lib/verify";
import { Button, Card, CardContent } from "@ai-search-growth-os/ui";

/**
 * "Since your last fixes" — the VERIFY strip. Every number here is read
 * from real audits and real status changes:
 * - verified / still detected: resolutions from the previous audit checked
 *   against the latest audit's observations (same code + page).
 * - awaiting: resolutions no completed audit has measured yet.
 * - the score delta names the two audits it compares; no other baseline is
 *   ever invented.
 * States and language must distinguish "action recorded" from "verified by
 * later measurement" — see lib/verify.ts.
 */
export function VerifyStrip({
  verification,
  canRunAudit,
  auditRunning,
  onRunAudit,
  issuesHref = "/app/geo/technical-seo",
}: {
  verification: VerificationSummary | null;
  canRunAudit: boolean;
  auditRunning: boolean;
  onRunAudit: () => void;
  issuesHref?: string;
}) {
  if (!verification) return null;
  const { verified, reappeared, awaiting, scoreDelta, latestAudit, previousAudit } = verification;
  const hasOutcome = verified.length > 0 || reappeared.length > 0;
  const hasAnything = hasOutcome || awaiting.length > 0;

  return (
    <Card className="py-4">
      <CardContent className="flex flex-col gap-3 px-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">Since your last fixes</p>
          <p className="text-muted-foreground text-xs">
            Last measured {relativeTime(latestAudit.completed_at, "–")}
          </p>
        </div>

        {!hasAnything ? (
          <p className="text-muted-foreground text-sm">
            No fixes recorded {previousAudit ? "between the last two audits" : "since the last audit"} yet. Resolve
            issues or approve agent proposals, then run a new audit to see whether they hold up.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {hasOutcome && (
                <>
                  <span className="inline-flex items-center gap-1.5">
                    <CheckCircle2Icon className="text-success size-4" aria-hidden="true" />
                    <strong className="tabular-nums">{verified.length}</strong> verified — no longer detected in the
                    latest audit
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <RotateCcwIcon className="text-warning size-4" aria-hidden="true" />
                    <strong className="tabular-nums">{reappeared.length}</strong> still detected
                  </span>
                </>
              )}
              {awaiting.length > 0 && (
                <span className="inline-flex items-center gap-1.5">
                  <TimerIcon className="text-muted-foreground size-4" aria-hidden="true" />
                  <strong className="tabular-nums">{awaiting.length}</strong> awaiting the next measurement
                </span>
              )}
              {hasOutcome && scoreDelta != null && previousAudit && (
                <span className="text-muted-foreground">
                  Technical SEO Health {scoreDelta > 0 ? "+" : ""}
                  {scoreDelta} pts between the {fmtDateFull(previousAudit.completed_at)} and{" "}
                  {fmtDateFull(latestAudit.completed_at)} audits
                </span>
              )}
            </div>
            {verified.length > 0 && (
              <p className="text-muted-foreground text-xs">
                Verified: {verified.slice(0, 3).map((o) => o.title).join(" · ")}
                {verified.length > 3 ? ` · +${verified.length - 3} more` : ""}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {awaiting.length > 0 && (
                <Button size="sm" disabled={!canRunAudit || auditRunning} onClick={onRunAudit}>
                  {auditRunning ? "Audit running…" : "Run a new audit to verify"}
                </Button>
              )}
              <Button asChild size="sm" variant="outline">
                <Link href={issuesHref}>View issues</Link>
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
