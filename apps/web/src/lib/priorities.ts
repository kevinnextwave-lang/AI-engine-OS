/**
 * Priorities: pure composition over data the product already stores.
 *
 * The primary source is the latest usable Research Agent run — its findings
 * already carry the product's canonical prioritisation (priority_score,
 * computed server-side with published weights) and pair index-for-index with
 * the run's recommendations, whose expected_area_of_impact is a fixed
 * backend vocabulary. That vocabulary maps to the ACT surfaces wired in
 * Phase C.
 *
 * Content gaps and alerts are shown as ADJACENT queues, never merged into
 * the findings ranking: their scores (opportunity 0–100, alert severity)
 * are not commensurable with finding priority scores, and inventing a
 * cross-source ranking would be fabricated precision.
 */

import type { AgentRun, CompetitiveAlertType } from "@ai-search-growth-os/types";

/** Where each research-declared impact area is acted on (Phase C surfaces).
 * Keys are the backend's fixed expected_area_of_impact vocabulary. */
export const AREA_DESTINATION: Record<string, { href: string; label: string }> = {
  "competitive AI visibility": { href: "/app/ai-visibility/competitors", label: "Review competitor comparison" },
  "citation footprint": { href: "/app/ai-intelligence/citation-gaps", label: "Review citation gaps" },
  "content coverage": { href: "/app/competitive/content-gaps", label: "Review content gaps" },
  "entity clarity": { href: "/app/geo/structured-data", label: "Review structured data" },
  "technical foundation": { href: "/app/geo/technical-seo", label: "Review technical SEO" },
  "evidence footprint": { href: "/app/geo/content", label: "Review content signals" },
  "competitive coverage": { href: "/app/competitive/discovery", label: "Review competitor candidates" },
};

/** Where each alert type is investigated (same map Phase C added to the
 * alerts drawer, hoisted here so both surfaces share one source). */
export const ALERT_DESTINATION: Partial<Record<CompetitiveAlertType, { href: string; label: string; hint: string }>> = {
  competitor_overtakes_brand: { href: "/app/ai-visibility/competitors", label: "Review competitor comparison", hint: "Opens the measured mention shares and the evidence behind them." },
  competitor_visibility_jump: { href: "/app/ai-visibility/competitors", label: "Review competitor comparison", hint: "Opens the measured mention shares and the evidence behind them." },
  new_competitor: { href: "/app/competitive/discovery", label: "Review competitor candidates", hint: "Confirm or reject what discovery found." },
  visibility_drop: { href: "/app/ai-visibility/trends", label: "Review visibility trend", hint: "See when the drop happened and at what confidence." },
  new_citation_source: { href: "/app/ai-intelligence/sources", label: "Review cited sources", hint: "Opens the source profiles behind recent answers." },
  citation_gap_increase: { href: "/app/ai-intelligence/citation-gaps", label: "Review citation gaps", hint: "The sources citing competitors but not you." },
  new_competitor_claim: { href: "/app/ai-intelligence/claims", label: "Review competitor claims", hint: "What AI answers assert about competitors." },
  content_gap: { href: "/app/competitive/content-gaps", label: "Review content gaps", hint: "Topics where competitors have coverage you lack." },
};

export interface PriorityFinding {
  /** Canonical identity: the run it came from + its index in that run. */
  runId: string;
  index: number;
  title: string;
  impact: string | null;
  confidence: string | null;
  priorityScore: number | null;
  observed: string | null;
  inference: string | null;
  recommendation: string | null;
  evidence: Record<string, unknown>;
  /** Backend-declared area this work is expected to improve. */
  area: string | null;
  /** The paired recommendation's concrete action text, when stored. */
  recommendedAction: string | null;
  whyNow: string | null;
  action: { href: string; label: string } | null;
}

interface RawFinding {
  title?: string;
  impact?: string;
  confidence?: string;
  priority_score?: number;
  statements?: Record<string, string>;
  evidence?: Record<string, unknown>;
}
interface RawRecommendation {
  title?: string;
  why_now?: string;
  recommended_action?: string;
  expected_area_of_impact?: string;
}

/** The newest run that actually produced findings; statuses that carry a
 * result in the existing model are completed and awaiting_approval. */
export function latestResearchRun(runs: AgentRun[]): AgentRun | null {
  return (
    runs
      .filter(
        (r) =>
          r.agent_name === "research" &&
          (r.status === "completed" || r.status === "awaiting_approval") &&
          Array.isArray((r.result as { findings?: unknown[] } | null)?.findings) &&
          ((r.result as { findings?: unknown[] }).findings?.length ?? 0) > 0,
      )
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0] ?? null
  );
}

/** Findings in the run's own stored order (already ranked by priority_score
 * server-side); recommendations pair index-for-index with findings. */
export function priorityFindings(run: AgentRun): PriorityFinding[] {
  const result = (run.result ?? {}) as { findings?: RawFinding[]; recommendations?: RawRecommendation[] };
  const findings = result.findings ?? [];
  const recs = result.recommendations ?? [];
  return findings.map((f, i) => {
    const rec = recs[i] ?? null;
    const area = rec?.expected_area_of_impact ?? null;
    // Content-coverage findings carry the gap's real topic and score in
    // their evidence — enough for the Phase C draft-a-brief handoff, which
    // beats sending the user back to the gap list.
    const topic = typeof f.evidence?.topic === "string" ? f.evidence.topic : null;
    const score = typeof f.evidence?.opportunity_score === "number" ? f.evidence.opportunity_score : null;
    const action =
      area === "content coverage" && topic
        ? {
            href: `/app/agents?agent=content-strategy&objective=${encodeURIComponent(
              `Draft a content brief for “${topic}”${score != null ? ` — opportunity score ${Math.round(score)}/100` : ""}${f.confidence ? ` (${f.confidence} confidence)` : ""}.`,
            )}`,
            label: rec?.recommended_action ?? "Draft a content brief",
          }
        : area
          ? (AREA_DESTINATION[area] ?? null)
          : null;
    return {
      runId: run.id,
      index: i,
      title: f.title ?? "Finding",
      impact: f.impact ?? null,
      confidence: f.confidence ?? null,
      priorityScore: typeof f.priority_score === "number" ? f.priority_score : null,
      observed: f.statements?.observed ?? null,
      inference: f.statements?.inference ?? null,
      recommendation: f.statements?.recommendation ?? null,
      evidence: f.evidence ?? {},
      area,
      recommendedAction: rec?.recommended_action ?? null,
      whyNow: rec?.why_now ?? null,
      action,
    };
  });
}

/** Canonical content-gap ids already covered by the given findings
 * (research stores the gap's id in the finding's evidence). */
export function coveredGapIds(findings: PriorityFinding[]): Set<string> {
  const ids = new Set<string>();
  for (const f of findings) {
    const id = f.evidence?.content_gap_id;
    if (typeof id === "string") ids.add(id);
  }
  return ids;
}

/** Existing severity semantics for ordering alert queues. */
export const ALERT_SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
