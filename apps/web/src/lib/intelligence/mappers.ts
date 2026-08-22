/** API contract → view models. Pure; never invents a value. */

import type {
  CitationGap,
  CitationGapSummary,
  CitationListItem,
  GraphClaimNode,
  GraphOverview,
  GraphSourceNode,
} from "@ai-search-growth-os/types";

import { providerLabel } from "@/lib/visibility/labels";

import { PRIORITY_LABEL } from "./labels";
import type {
  CitationRow,
  ClaimRow,
  IntelligenceMetric,
  OpportunityCard,
  SourceDetail,
  SourceRow,
  TopSourceBar,
} from "./types";

function pct(n: number, total: number): number | null {
  return total > 0 ? Math.round((1000 * n) / total) / 10 : null;
}

export function overviewMetrics(graph: GraphOverview | null, gaps: CitationGapSummary | null): IntelligenceMetric[] {
  const st = graph?.statistics ?? null;
  const citations = st?.citations ?? 0;
  return [
    {
      key: "citations",
      label: "Total citations",
      value: st ? st.citations : null,
      unit: "count",
      note: "Citations found in parsed AI responses in the selected window.",
    },
    {
      key: "sources",
      label: "Unique sources",
      value: st ? st.source_domains : null,
      unit: "count",
      note: "Distinct source domains cited.",
    },
    {
      key: "brand_rate",
      label: "Brand citation rate",
      value: st ? pct(st.brand_citations, citations) : null,
      unit: "percent",
      note: "Share of citations that point at your domains or name you in the cited URL.",
    },
    {
      key: "competitor_rate",
      label: "Competitor citation rate",
      value: st ? pct(st.competitor_citations, citations) : null,
      unit: "percent",
      note: "Share of citations that point at a configured competitor or name one in the cited URL.",
    },
    {
      key: "gaps",
      label: "Citation gap opportunities",
      value: gaps ? gaps.actionable : null,
      unit: "count",
      note: "Open gaps with at least low confidence and an opportunity score of 40 or more.",
    },
  ];
}

export function topSources(items: GraphSourceNode[], limit = 10): TopSourceBar[] {
  return items.slice(0, limit).map((s) => ({
    sourceDomainId: s.source_domain_id,
    domain: s.display_name || s.domain,
    sourceType: s.source_type,
    citations: s.citations,
    brandCitations: s.brand_citations,
    competitorCitations: s.competitor_citations,
  }));
}

export function opportunityCard(gap: CitationGap, brandName: string): OpportunityCard {
  const rows = Object.entries(gap.competitors)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([name, citations]) => ({ name, citations, isBrand: false }));
  rows.push({ name: brandName, citations: gap.brand_citations, isBrand: true });
  return { gap, priorityLabel: PRIORITY_LABEL[gap.priority], rows };
}

export function sourceRows(items: GraphSourceNode[], gaps: CitationGap[]): SourceRow[] {
  const gapByDomain = new Map(gaps.map((g) => [g.source_domain_id, g]));
  return items.map((s) => {
    const gap = gapByDomain.get(s.source_domain_id) ?? null;
    return {
      sourceDomainId: s.source_domain_id,
      domain: s.domain,
      displayName: s.display_name,
      sourceType: s.source_type,
      citations: s.citations,
      responses: s.responses,
      prompts: s.prompts,
      brandCitations: s.brand_citations,
      competitorCitations: s.competitor_citations,
      competitors: s.competitors,
      firstCitedAt: s.first_cited_at,
      lastCitedAt: s.last_cited_at,
      topPages: s.top_pages.map((p) => ({ url: p.url, citations: p.citations })),
      opportunity: gap ? gap.opportunity_score : null,
      gap,
    };
  });
}

export function claimRows(items: GraphClaimNode[]): ClaimRow[] {
  return items.map((c) => ({
    key: `${c.subject}|${c.predicate}|${c.object}`,
    subject: c.subject,
    predicate: c.predicate,
    object: c.object,
    occurrences: c.occurrences,
    responses: c.responses,
    prompts: c.prompts,
    confidence: c.avg_confidence,
    associatedWith: c.associated_with,
    entityName: c.entity_name,
    example: c.examples[0] ?? null,
    lastSeenAt: c.last_seen_at,
  }));
}

export function citationRows(items: CitationListItem[]): CitationRow[] {
  return items.map((c) => ({
    id: c.id,
    url: c.url,
    domain: c.domain,
    sourceDomainId: c.source_domain_id,
    sourceType: c.source_type,
    citedAt: c.cited_at,
    prompt: c.prompt,
    promptId: c.prompt_id,
    runId: c.prompt_run_id,
    provider: c.provider_key,
    providerLabel: c.provider_key ? providerLabel(c.provider_key) : "–",
    model: c.model_key,
    relationships: c.relationships.map((r) => ({ name: r.entity_name, relationship: r.relationship, confidence: r.confidence })),
  }));
}

function weekStart(iso: string): string {
  const d = new Date(iso);
  const day = (d.getUTCDay() + 6) % 7; // Monday = 0
  d.setUTCDate(d.getUTCDate() - day);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

/** Everything the source drawer shows, derived from that source's citations. */
export function sourceDetail(row: SourceRow, citations: CitationListItem[], total: number): SourceDetail {
  const count = <K extends string>(keys: K[]): Map<K, number> => {
    const m = new Map<K, number>();
    for (const k of keys) m.set(k, (m.get(k) ?? 0) + 1);
    return m;
  };
  const pages = [...count(citations.map((c) => c.url ?? "").filter(Boolean))]
    .map(([url, n]) => ({ url, citations: n }))
    .sort((a, b) => b.citations - a.citations);
  const engineKey = (c: CitationListItem) => `${c.provider_key ?? "?"}|${c.model_key ?? ""}`;
  const engines = [...count(citations.map(engineKey))]
    .map(([k, n]) => {
      const [provider, model] = k.split("|");
      return { provider: provider ?? "?", label: providerLabel(provider ?? "?"), model: model || null, citations: n };
    })
    .sort((a, b) => b.citations - a.citations);
  const rel = (kind: string) =>
    [...count(citations.flatMap((c) => c.relationships.filter((r) => r.relationship === kind).map((r) => r.entity_name)))]
      .map(([name, n]) => ({ name, citations: n }))
      .sort((a, b) => b.citations - a.citations);
  const trend = [...count(citations.filter((c) => c.cited_at).map((c) => weekStart(c.cited_at as string)))]
    .map(([weekStart, n]) => ({ weekStart, citations: n }))
    .sort((a, b) => a.weekStart.localeCompare(b.weekStart));
  const promptCounts = new Map<string, { prompt: string; n: number }>();
  for (const c of citations) {
    const cur = promptCounts.get(c.prompt_id) ?? { prompt: c.prompt, n: 0 };
    cur.n += 1;
    promptCounts.set(c.prompt_id, cur);
  }
  const prompts = [...promptCounts]
    .map(([promptId, v]) => ({ promptId, prompt: v.prompt, citations: v.n }))
    .sort((a, b) => b.citations - a.citations);
  return {
    row,
    pages,
    engines,
    brands: rel("brand"),
    competitors: rel("competitor"),
    trend,
    prompts,
    citationsLoaded: citations.length,
    citationsTotal: total,
  };
}
