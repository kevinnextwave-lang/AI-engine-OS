/**
 * Builders for the app-wide "AI Recommendation" pattern (AiInsight).
 *
 * Every builder is a pure function over data the product has already
 * measured and stored: audit observations, structured-data analysis,
 * response-share measurements and citation-gap analysis. Each returns null
 * when the underlying data does not exist — a surface without data shows
 * nothing rather than an invented insight.
 *
 * Language rules: headlines state measured facts; "why it matters" explains
 * mechanism in cautious language ("can", "makes it easier/harder"); no
 * builder ever projects an outcome ("will increase traffic by N%").
 */

import type { AiEvidenceFact } from "@ai-search-growth-os/ui";
import type { CitationGap } from "@ai-search-growth-os/types";

import { relativeTime } from "@/lib/geo/mappers";
import type { AiRecommendation, PriorityOpportunity } from "@/lib/geo/overview";
import type { AuditSummary, StructuredDataOverview } from "@/lib/geo/types";
import type { GeoIssue } from "@/lib/geo/types";
import type { CompetitorShareRow } from "@/lib/visibility/types";

export interface InsightModel {
  headline: string;
  whyItMatters: string;
  /** One or more concrete actions, most important first. */
  actions: string[];
  evidence: AiEvidenceFact[];
  /** Provenance: which stored analysis this is read from, and how old it is. */
  source: string;
  ctaLabel: string;
}

// --- GEO overview: audit findings → action plan ----------------------------

export function geoActionPlanInsight(input: {
  summary: AuditSummary;
  opportunities: PriorityOpportunity[];
  recommendations: AiRecommendation[];
  pagesAnalyzed: number;
  auditTimestamp: string | null;
}): InsightModel | null {
  const { summary, opportunities, recommendations, pagesAnalyzed, auditTimestamp } = input;
  const open = summary.critical + summary.high + summary.medium + summary.low;
  if (open === 0 || opportunities.length === 0 || !auditTimestamp) return null;
  const top = opportunities[0]!;
  const reach =
    top.affectedCount > 0 ? ` The most significant: “${top.title}” (${top.affectedCount} ${top.affectedCount === 1 ? "page" : "pages"}).` : "";
  return {
    headline: `The latest audit found ${open} open finding${open === 1 ? "" : "s"} across ${pagesAnalyzed} analyzed pages.${reach}`,
    whyItMatters:
      "Each finding is a measured obstacle to how reliably crawlers and AI systems can fetch, understand or cite this site. Fixing them removes ambiguity; none of this guarantees ranking changes.",
    actions: (recommendations.length > 0 ? recommendations.map((r) => r.action) : opportunities.map((o) => o.action)).slice(0, 3),
    evidence: (
      [
        summary.critical > 0 ? { label: "Critical", value: summary.critical } : null,
        summary.high > 0 ? { label: "High", value: summary.high } : null,
        summary.medium > 0 ? { label: "Medium", value: summary.medium } : null,
        summary.low > 0 ? { label: "Low", value: summary.low } : null,
        { label: "Pages analyzed", value: pagesAnalyzed },
      ] as Array<AiEvidenceFact | null>
    ).filter((f): f is AiEvidenceFact => f !== null),
    source: `From the technical SEO and AI readiness audits · ${relativeTime(auditTimestamp)}`,
    ctaLabel: "Review top issue",
  };
}

// --- AI Visibility: summarize competitor differences ------------------------

export function competitorGapInsight(input: {
  brandName: string;
  competitors: CompetitorShareRow[];
  competitorsAhead: CompetitorShareRow[];
  sampleSize: number;
}): InsightModel | null {
  const { brandName, competitors, competitorsAhead, sampleSize } = input;
  const brand = competitors.find((c) => c.isBrand);
  // Needs a measured brand row, configured competitors and any sample at all.
  if (!brand || competitors.length <= 1 || sampleSize === 0 || competitorsAhead.length === 0) return null;
  const ahead = competitorsAhead.slice(0, 3);
  const list = ahead.map((c) => `${c.name} (${c.mentionRate ?? 0}%)`).join(", ");
  return {
    headline: `${competitorsAhead.length} configured competitor${competitorsAhead.length === 1 ? " is" : "s are"} mentioned more often than ${brandName} in this period's AI answers: ${list} vs ${brand.mentionRate ?? 0}%.`,
    whyItMatters:
      "Mention share shows whose names AI engines reach for on your buyer prompts. It is a measured share of this period's responses — not a market-share or ranking claim.",
    actions: [
      `Open the prompts where ${ahead[0]!.name} appears and read those responses to see how it is described.`,
      "Check Citation Intelligence for the sources those answers cite — citation gaps there are the most direct levers this product measures.",
    ],
    evidence: [
      { label: `${brandName} mention rate`, value: `${brand.mentionRate ?? 0}%` },
      ...ahead.map((c) => ({ label: c.name, value: `${c.mentionRate ?? 0}%` })),
      { label: "Responses", value: `n = ${sampleSize}` },
    ],
    source: "From measured AI responses in the selected period",
    ctaLabel: "Compare competitors",
  };
}

// --- Structured data --------------------------------------------------------

export function structuredDataInsight(sd: StructuredDataOverview): InsightModel | null {
  if (sd.pagesCrawled === 0) return null;
  const coverage = Math.round((100 * sd.pagesWithSchema) / sd.pagesCrawled);
  if (sd.pagesWithoutSchema === 0 && sd.blocksInvalid === 0) return null;
  const missing = sd.knownTypesAbsent.slice(0, 4);
  return {
    headline: `${sd.pagesWithoutSchema} of ${sd.pagesCrawled} crawled pages (${100 - coverage}%) declare no structured data.`,
    whyItMatters:
      "Structured data gives machines an explicit, unambiguous statement of what a page is about. Pages without it leave crawlers and AI systems to infer facts from prose, which is less reliable.",
    actions: [
      "Review the highest-value pages without markup and add the types that genuinely describe them.",
      ...(missing.length > 0
        ? [`Consider the tracked types this site doesn't use anywhere yet: ${missing.join(", ")}${sd.knownTypesAbsent.length > missing.length ? "…" : ""}. Not every site needs every type.`]
        : []),
      ...(sd.blocksInvalid > 0 ? [`Fix the ${sd.blocksInvalid} block${sd.blocksInvalid === 1 ? "" : "s"} that could not be parsed.`] : []),
    ],
    evidence: [
      { label: "Coverage", value: `${coverage}%` },
      { label: "Pages without schema", value: sd.pagesWithoutSchema },
      { label: "Invalid blocks", value: sd.blocksInvalid },
      { label: "Tracked types absent", value: sd.knownTypesAbsent.length },
    ],
    source: `From the structured data analysis${sd.analyzedAt ? ` · ${relativeTime(sd.analyzedAt)}` : ""}`,
    ctaLabel: "Review pages",
  };
}

// --- Content -----------------------------------------------------------------

export function contentInsight(input: {
  issues: GeoIssue[];
  contentScore: number | null;
  auditTimestamp: string | null;
}): InsightModel | null {
  const open = input.issues.filter((i) => i.status === "open" && i.severity !== "info");
  if (open.length === 0) return null;
  const top = open[0]!;
  return {
    headline: `${open.length} content finding${open.length === 1 ? " is" : "s are"} open; the most significant: “${top.title}”${top.affectedCount > 0 ? ` (${top.affectedCount} ${top.affectedCount === 1 ? "page" : "pages"})` : ""}.`,
    whyItMatters:
      "Specific, well-structured, attributable content is easier for AI systems to quote and cite accurately. These findings mark where the audit measured that quality falling short.",
    actions: [...new Set(open.map((i) => i.recommendation))].slice(0, 3),
    evidence: [
      ...(input.contentScore != null ? [{ label: "Content Quality", value: `${input.contentScore}/100` }] : []),
      { label: "Open findings", value: open.length },
      { label: "Categories", value: new Set(open.map((i) => i.category)).size },
    ],
    source: `From the content-side audit observations${input.auditTimestamp ? ` · ${relativeTime(input.auditTimestamp)}` : ""}`,
    ctaLabel: "Draft a content brief",
  };
}

// --- Citation gaps -----------------------------------------------------------

const GAP_ACTION: Record<string, string> = {
  brand_absent:
    "This source never cites you. Review what competitors have published or listed there and pursue equivalent coverage or presence where appropriate.",
  competitor_advantage:
    "Competitors are cited from this source more than you. Review the cited pages to see what earns their citations.",
  source_underrepresented:
    "This source appears in relevant answers more than your presence on it reflects. Evaluate whether stronger coverage there is achievable.",
  source_overrepresented:
    "Your visibility leans heavily on this one source. Consider broadening the sources that cite you to reduce concentration.",
  shared_source:
    "You and competitors are both cited here. Review the cited pages to understand how each brand is represented.",
  emerging_source:
    "This source recently started appearing in relevant answers. Review it early, while coverage there is still forming.",
};

/** Gap statuses that still need attention (not dismissed or completed). */
const ACTIONABLE_GAP_STATUS = new Set(["new", "reviewing", "accepted", "in_progress"]);

/** Highest-priority actionable gap; the CTA target for the citation-gaps insight. */
export function topOpenGap(gaps: CitationGap[]): CitationGap | null {
  const open = gaps.filter((g) => ACTIONABLE_GAP_STATUS.has(g.status));
  if (open.length === 0) return null;
  const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
  return [...open].sort(
    (a, b) => (order[a.priority] ?? 3) - (order[b.priority] ?? 3) || b.opportunity_score - a.opportunity_score,
  )[0]!;
}

export function citationGapInsight(gaps: CitationGap[]): InsightModel | null {
  const open = gaps.filter((g) => ACTIONABLE_GAP_STATUS.has(g.status));
  const top = topOpenGap(gaps);
  if (!top) return null;
  return {
    headline: `${top.display_name || top.domain} appears in ${top.relevant_response_count} relevant AI answer${top.relevant_response_count === 1 ? "" : "s"} — cited ${top.competitor_citations} time${top.competitor_citations === 1 ? "" : "s"} for competitors and ${top.brand_citations} for you.`,
    // The gap analysis writes its own explanation from the measured counts.
    whyItMatters: top.explanation,
    actions: [GAP_ACTION[top.gap_type] ?? "Review the gap's cited pages and decide whether this source is worth pursuing."],
    evidence: [
      { label: "Competitor citations", value: top.competitor_citations },
      { label: "Your citations", value: top.brand_citations },
      { label: "Relevant responses", value: top.relevant_response_count },
      { label: "Priority", value: top.priority },
      { label: "Confidence", value: top.confidence },
    ],
    source: `From the citation gap analysis (${open.length} open gap${open.length === 1 ? "" : "s"})`,
    ctaLabel: "Review gap",
  };
}
