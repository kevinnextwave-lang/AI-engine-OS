/**
 * The VERIFY layer: pure functions relating user actions to LATER
 * measurements, built only from data the backend already stores.
 *
 * Ground rules (enforced here, not just in copy):
 * - Nothing is "verified" because someone clicked a button. Verified means:
 *   the issue was marked resolved, and a technical audit COMPLETED AFTER
 *   that resolution no longer detects the same issue.
 * - Issue identity across audits is the backend's own stable key: the
 *   observation `code` plus the affected `url` (audits create fresh
 *   observation rows each run; code+url is how the same check on the same
 *   page reappears).
 * - Chronology is respected: a resolution AFTER the latest audit completed
 *   cannot be verified by it — it is awaiting the next measurement.
 * - No baselines are invented: every delta names the two real audits it
 *   compares.
 */

import type { SeoAudit, SeoObservation } from "@ai-search-growth-os/types";

/** Stable identity of an observed issue across audits. */
export function observationKey(o: Pick<SeoObservation, "code" | "url">): string {
  return `${o.code}::${o.url ?? ""}`;
}

export type IssueVerification = "awaiting" | "reappeared" | null;

export interface VerificationSummary {
  /** The audit that did the verifying (latest completed). */
  latestAudit: SeoAudit;
  /** The audit the resolutions came from (previous completed), if any. */
  previousAudit: SeoAudit | null;
  /** Resolved before the latest audit ran and no longer detected by it. */
  verified: SeoObservation[];
  /** Resolved before the latest audit ran but detected again by it. */
  reappeared: SeoObservation[];
  /** Marked resolved with no completed audit after the resolution yet. */
  awaiting: SeoObservation[];
  /** Real score movement between the two audits (latest − previous). */
  scoreDelta: number | null;
}

/**
 * Relates resolutions to the next completed audit.
 *
 * @param latestAudit    newest completed technical audit
 * @param latestObs      its observations
 * @param previousAudit  the completed audit before it (null if none)
 * @param previousObs    its observations (empty if none)
 */
export function verificationSummary(
  latestAudit: SeoAudit | null,
  latestObs: SeoObservation[],
  previousAudit: SeoAudit | null,
  previousObs: SeoObservation[],
): VerificationSummary | null {
  if (!latestAudit?.completed_at) return null;
  const latestCompleted = Date.parse(latestAudit.completed_at);
  const latestKeys = new Set(latestObs.map(observationKey));

  const verified: SeoObservation[] = [];
  const reappeared: SeoObservation[] = [];
  const awaiting: SeoObservation[] = [];

  // Resolutions recorded on the previous audit's observations: the latest
  // audit can verify exactly those made BEFORE it completed.
  for (const o of previousObs) {
    if (o.status !== "resolved") continue;
    const resolvedAt = Date.parse(o.updated_at);
    if (Number.isFinite(resolvedAt) && resolvedAt < latestCompleted) {
      (latestKeys.has(observationKey(o)) ? reappeared : verified).push(o);
    } else {
      awaiting.push(o); // resolved after the measurement — nothing can confirm it yet
    }
  }
  // Resolutions on the latest audit's own observations are by definition
  // newer than that audit's measurement.
  for (const o of latestObs) {
    if (o.status === "resolved") awaiting.push(o);
  }

  const scoreDelta =
    previousAudit?.health_score != null && latestAudit.health_score != null
      ? Math.round((latestAudit.health_score - previousAudit.health_score) * 10) / 10
      : null;

  return { latestAudit, previousAudit, verified, reappeared, awaiting, scoreDelta };
}

/** Per-issue verification state for the LATEST audit's rows (what the issue
 * tables display): resolved rows await the next audit; open rows whose key
 * was resolved against the previous audit have reappeared. */
export function issueVerification(
  o: Pick<SeoObservation, "code" | "url" | "status">,
  previouslyResolvedKeys: ReadonlySet<string>,
): IssueVerification {
  if (o.status === "resolved") return "awaiting";
  if (o.status === "open" && previouslyResolvedKeys.has(observationKey(o))) return "reappeared";
  return null;
}

export function previouslyResolvedKeys(previousObs: SeoObservation[]): Set<string> {
  return new Set(previousObs.filter((o) => o.status === "resolved").map(observationKey));
}

// --- Chart events -----------------------------------------------------------

export interface ChartEvent {
  /** Epoch ms of the event. */
  ts: number;
  /** Short factual label, e.g. "Research Agent run" / "3 issues marked resolved". */
  label: string;
  /** One-line detail for the accessible tooltip. */
  detail: string;
}

/** Groups events that fall on the same day into one marker ("3 changes"),
 * keeping charts readable without dropping information. */
export function groupEventsByDay(events: ChartEvent[]): ChartEvent[] {
  const byDay = new Map<string, ChartEvent[]>();
  for (const e of events) {
    const day = new Date(e.ts).toISOString().slice(0, 10);
    const g = byDay.get(day);
    if (g) g.push(e);
    else byDay.set(day, [e]);
  }
  const out: ChartEvent[] = [];
  for (const group of byDay.values()) {
    if (group.length === 1) {
      out.push(group[0]!);
    } else {
      const sorted = [...group].sort((a, b) => a.ts - b.ts);
      out.push({
        ts: sorted[0]!.ts,
        label: `${group.length} changes`,
        detail: sorted.map((e) => e.label).join(" · "),
      });
    }
  }
  return out.sort((a, b) => a.ts - b.ts);
}
