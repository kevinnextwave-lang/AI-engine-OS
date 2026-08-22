/**
 * Sample data for the Citation Intelligence section. Shown ONLY when no project
 * is selected or the API cannot be reached, always behind the "Mock data"
 * badge. A selected project with too little data shows the empty state.
 */

import type {
  CitationGap,
  CitationGapSummary,
  CitationListItem,
  GraphClaimsResponse,
  GraphOverview,
  GraphSourcesResponse,
} from "@ai-search-growth-os/types";

export const MOCK_BRAND = "Acme Analytics";
const NOW = new Date("2026-08-22T12:00:00Z");
const iso = (daysAgo: number) => new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();
const WINDOW = { start: iso(90), end: iso(0) };
const PID = "mock-project";

type SourceSeed = [id: string, domain: string, type: GraphSourcesResponse["items"][number]["source_type"], n: number, brand: number, comp: Record<string, number>];
const SOURCES: SourceSeed[] = [
  ["sd-g2", "g2.com", "review", 42, 3, { "Northwind BI": 31, "Contoso Insights": 24 }],
  ["sd-reddit", "reddit.com", "community", 31, 6, { "Northwind BI": 12 }],
  ["sd-forbes", "forbes.com", "media", 21, 0, { "Northwind BI": 9, "Fabrikam Data": 4 }],
  ["sd-capterra", "capterra.com", "review", 18, 2, { "Contoso Insights": 11, "Northwind BI": 7 }],
  ["sd-acme", "acme-analytics.example", "company", 15, 15, {}],
  ["sd-northwind", "northwindbi.example", "company", 14, 0, { "Northwind BI": 14 }],
  ["sd-medium", "medium.com", "blog", 9, 1, { "Fabrikam Data": 2 }],
  ["sd-techcrunch", "techcrunch.com", "media", 7, 0, { "Northwind BI": 3 }],
];

export const MOCK_SOURCES: GraphSourcesResponse = {
  version: "ai-search-graph/v1",
  project_id: PID,
  window: WINDOW,
  view: "top",
  items: SOURCES.map(([id, domain, type, n, brand, comp], i) => ({
    source_domain_id: id,
    domain,
    display_name: domain,
    source_type: type,
    citations: n,
    responses: Math.round(n * 0.8),
    prompts: Math.min(8, Math.ceil(n / 4)),
    brand_citations: brand,
    competitor_citations: Object.values(comp).reduce((a, b) => a + b, 0),
    competitors: comp,
    first_cited_at: iso(80 - i * 5),
    last_cited_at: iso(i % 3),
    competitor_share: null,
    brand_ratio: null,
    previous_citations: null,
    growth: null,
    top_pages: [
      { source_page_id: `${id}-p1`, url: `https://${domain}/products/northwind-bi`, citations: Math.round(n * 0.5) },
      { source_page_id: `${id}-p2`, url: `https://${domain}/compare/analytics-tools`, citations: Math.round(n * 0.3) },
    ],
  })),
  total: SOURCES.length,
  limit: 50,
  offset: 0,
};

function gap(
  id: string,
  seed: SourceSeed,
  gap_type: CitationGap["gap_type"],
  score: number,
  confidence: CitationGap["confidence"],
  explanation: string,
): CitationGap {
  const [sid, domain, type, n, brand, comp] = seed;
  return {
    id,
    project_id: PID,
    source_domain_id: sid,
    source_page_id: null,
    domain,
    display_name: domain,
    source_type: type,
    gap_type,
    priority: score >= 70 ? "high" : score >= 40 ? "medium" : "low",
    brand_citations: brand,
    competitor_citations: Object.values(comp).reduce((a, b) => a + b, 0),
    competitors: comp,
    relevant_response_count: Math.round(n * 0.8),
    opportunity_score: score,
    confidence,
    explanation,
    status: "new",
    note: null,
    evidence: {
      score,
      components: {
        citation_frequency: { value: Math.min(100, n * 2), weight: 25 },
        competitor_gap: { value: brand === 0 ? 100 : 85, weight: 30 },
        source_relevance: { value: 68, weight: 20 },
        prompt_relevance: { value: 60, weight: 15 },
        recency: { value: 100, weight: 10 },
      },
      inputs: { eligible_responses: 72, relevant_responses: Math.round(n * 0.8), total_prompts: 24, prompts_citing: 6 },
      window_days: 90,
      top_pages: [{ url: `https://${domain}/products/northwind-bi`, citations: Math.round(n * 0.5) }],
    },
    analysis_version: "citation-gaps/v1",
    analyzed_at: iso(0),
    created_at: iso(10),
    updated_at: iso(0),
  };
}

export const MOCK_GAPS: CitationGap[] = [
  gap("gap-g2", SOURCES[0]!, "competitor_advantage", 91, "high", "Competitors are frequently cited from g2.com (55 citations: Northwind BI (31), Contoso Insights (24)) while the brand is rarely cited (3). Based on 34 of 72 eligible responses across 6 prompts (high confidence)."),
  gap("gap-forbes", SOURCES[2]!, "brand_absent", 74, "medium", "forbes.com is cited in 17 relevant AI responses but never for the brand; competitors cited from it: Northwind BI (9), Fabrikam Data (4). Based on 17 of 72 eligible responses across 4 prompts (medium confidence)."),
  gap("gap-capterra", SOURCES[3]!, "competitor_advantage", 66, "medium", "Competitors are frequently cited from capterra.com (18 citations: Contoso Insights (11), Northwind BI (7)) while the brand is rarely cited (2). Based on 14 of 72 eligible responses across 5 prompts (medium confidence)."),
  gap("gap-reddit", SOURCES[1]!, "shared_source", 38, "high", "reddit.com cites both the brand (6) and competitors (12: Northwind BI (12)); parity rather than a gap. Based on 25 of 72 eligible responses across 7 prompts (high confidence)."),
  gap("gap-techcrunch", SOURCES[7]!, "emerging_source", 45, "low", "techcrunch.com started appearing recently and is being cited more and more (1 → 6 citations) without citing the brand. Based on 6 of 72 eligible responses across 2 prompts (low confidence)."),
  gap("gap-acme", SOURCES[4]!, "source_overrepresented", 14, "high", "acme-analytics.example cites the brand (15) and no competitor; the brand already dominates this source. Based on 12 of 72 eligible responses across 5 prompts (high confidence)."),
];

export const MOCK_GAP_SUMMARY: CitationGapSummary = {
  project_id: PID,
  analyzed_at: iso(0),
  analysis_version: "citation-gaps/v1",
  total: MOCK_GAPS.length,
  by_gap_type: { competitor_advantage: 2, brand_absent: 1, shared_source: 1, emerging_source: 1, source_overrepresented: 1 },
  by_status: { new: 6 },
  by_confidence: { high: 3, medium: 2, low: 1 },
  by_source_type: { review: 2, media: 2, community: 1, company: 1 },
  by_priority: { high: 2, medium: 2, low: 2 },
  actionable: 4,
  top_opportunities: MOCK_GAPS.slice(0, 4),
  competitors_ahead: { "Northwind BI": 2, "Fabrikam Data": 1 },
  data: { eligible_responses: 72, relevant_prompts: 24, sources_observed: 8, window_days: 90, sufficient: true, note: "Sample data." },
  method: "citation-gaps/v1",
};

const PROMPTS = [
  ["pr-1", "What are the best analytics platforms for mid-size SaaS companies?"],
  ["pr-2", "Acme Analytics vs Northwind BI: which is better for product teams?"],
  ["pr-3", "Affordable alternatives to Northwind BI"],
  ["pr-4", "Which BI tool has the best Snowflake integration?"],
] as const;

export const MOCK_GRAPH: GraphOverview = {
  version: "ai-search-graph/v1",
  project_id: PID,
  window: WINDOW,
  nodes: [
    { id: `project:${PID}`, type: "project", label: MOCK_BRAND, properties: {} },
    { id: `brand:${PID}`, type: "brand", label: MOCK_BRAND, properties: { mentions: 42, citations: 27 } },
    { id: "competitor:c-northwind", type: "competitor", label: "Northwind BI", properties: { mentions: 51, citations: 76, configured: true } },
    { id: "competitor:c-contoso", type: "competitor", label: "Contoso Insights", properties: { mentions: 39, citations: 35, configured: true } },
    { id: "competitor:c-fabrikam", type: "competitor", label: "Fabrikam Data", properties: { mentions: 22, citations: 6, configured: true } },
    ...PROMPTS.map(([id, text]) => ({ id: `prompt:${id}`, type: "prompt" as const, label: text, properties: { responses: 9, category: "comparison" } })),
    ...SOURCES.slice(0, 6).map(([id, domain, type, n]) => ({ id: `source_domain:${id}`, type: "source_domain" as const, label: domain, properties: { source_type: type, citations: n } })),
  ],
  edges: [
    { source: `project:${PID}`, target: `brand:${PID}`, type: "tracks", weight: 1, properties: {} },
    ...["c-northwind", "c-contoso", "c-fabrikam"].map((c) => ({ source: `project:${PID}`, target: `competitor:${c}`, type: "tracks" as const, weight: 1, properties: {} })),
    { source: `brand:${PID}`, target: "competitor:c-northwind", type: "competes_with", weight: 30, properties: {} },
    { source: `brand:${PID}`, target: "competitor:c-contoso", type: "competes_with", weight: 18, properties: {} },
    ...PROMPTS.map(([id]) => ({ source: `project:${PID}`, target: `prompt:${id}`, type: "has_prompt" as const, weight: 1, properties: {} })),
    { source: "prompt:pr-1", target: `brand:${PID}`, type: "mentions", weight: 9, properties: {} },
    { source: "prompt:pr-2", target: `brand:${PID}`, type: "mentions", weight: 9, properties: {} },
    { source: "prompt:pr-1", target: "competitor:c-northwind", type: "cites", weight: 12, properties: {} },
    { source: "prompt:pr-3", target: "competitor:c-northwind", type: "cites", weight: 8, properties: {} },
    { source: "prompt:pr-1", target: "source_domain:sd-g2", type: "cites", weight: 14, properties: {} },
    { source: "prompt:pr-2", target: "source_domain:sd-g2", type: "cites", weight: 10, properties: {} },
    { source: "prompt:pr-3", target: "source_domain:sd-capterra", type: "cites", weight: 8, properties: {} },
    { source: "prompt:pr-4", target: "source_domain:sd-reddit", type: "cites", weight: 11, properties: {} },
    { source: "prompt:pr-1", target: "source_domain:sd-forbes", type: "cites", weight: 7, properties: {} },
    { source: `brand:${PID}`, target: "source_domain:sd-acme", type: "associated_with", weight: 15, properties: { relationship: "brand" } },
    { source: `brand:${PID}`, target: "source_domain:sd-reddit", type: "associated_with", weight: 6, properties: { relationship: "brand" } },
    { source: "competitor:c-northwind", target: "source_domain:sd-g2", type: "associated_with", weight: 31, properties: { relationship: "competitor" } },
    { source: "competitor:c-contoso", target: "source_domain:sd-g2", type: "associated_with", weight: 24, properties: { relationship: "competitor" } },
    { source: "competitor:c-northwind", target: "source_domain:sd-northwind", type: "associated_with", weight: 14, properties: { relationship: "competitor" } },
    { source: "competitor:c-northwind", target: "source_domain:sd-forbes", type: "associated_with", weight: 9, properties: { relationship: "competitor" } },
    { source: "competitor:c-contoso", target: "source_domain:sd-capterra", type: "associated_with", weight: 11, properties: { relationship: "competitor" } },
  ],
  statistics: {
    responses: 72,
    prompts: 24,
    models: 3,
    brand_mentions: 42,
    competitor_mentions: 112,
    claims: 38,
    citations: 157,
    source_domains: 8,
    source_pages: 23,
    brand_citations: 27,
    competitor_citations: 117,
    provider: null,
    competitors_configured: 3,
    nodes_returned: 15,
    edges_returned: 23,
    truncated: true,
  },
};

export const MOCK_CLAIMS: GraphClaimsResponse = {
  version: "ai-search-graph/v1",
  project_id: PID,
  window: WINDOW,
  items: [
    { subject: "northwind bi", predicate: "offers", object: "native snowflake connector", occurrences: 14, responses: 14, prompts: 4, avg_confidence: 0.82, associated_with: "competitor", entity_name: "Northwind BI", first_seen_at: iso(60), last_seen_at: iso(1), examples: ["Northwind BI offers a native Snowflake connector."] },
    { subject: "acme analytics", predicate: "offers", object: "usage-based pricing", occurrences: 9, responses: 9, prompts: 3, avg_confidence: 0.74, associated_with: "brand", entity_name: MOCK_BRAND, first_seen_at: iso(40), last_seen_at: iso(2), examples: ["Acme Analytics offers usage-based pricing."] },
    { subject: "contoso insights", predicate: "is", object: "best for enterprise teams", occurrences: 7, responses: 7, prompts: 2, avg_confidence: 0.6, associated_with: "competitor", entity_name: "Contoso Insights", first_seen_at: iso(30), last_seen_at: iso(5), examples: ["Contoso Insights is best for enterprise teams."] },
    { subject: "fabrikam data", predicate: "has", object: "a free tier", occurrences: 4, responses: 4, prompts: 2, avg_confidence: 0.55, associated_with: "competitor", entity_name: "Fabrikam Data", first_seen_at: iso(20), last_seen_at: iso(3), examples: ["Fabrikam Data has a free tier."] },
  ],
  total: 4,
  limit: 50,
  offset: 0,
};

export const MOCK_CITATIONS: CitationListItem[] = SOURCES.flatMap(([id, domain, type, n, brand, comp], si) =>
  Array.from({ length: Math.min(n, 6) }, (_, i) => {
    const compName = Object.keys(comp)[i % Math.max(1, Object.keys(comp).length)];
    const isBrand = brand > 0 && i < Math.ceil((brand / n) * 6);
    return {
      id: `cit-${id}-${i}`,
      url: `https://${domain}/${isBrand ? "products/acme-analytics" : compName ? `products/${compName.toLowerCase().replace(/\s+/g, "-")}` : "articles/analytics-tools"}`,
      domain,
      source_domain_id: id,
      source_page_id: `${id}-p${i % 2}`,
      source_type: type,
      anchor_text: null,
      citation_type: "explicit_url",
      citation_position: i + 1,
      cited_at: iso(si * 3 + i * 7),
      prompt_id: PROMPTS[i % PROMPTS.length]![0],
      prompt: PROMPTS[i % PROMPTS.length]![1],
      prompt_run_id: `run-${id}-${i}`,
      provider_key: ["openai", "google", "anthropic"][i % 3] ?? "openai",
      model_key: ["gpt-4o-mini", "gemini-2.0-flash", "claude-3-5-haiku"][i % 3] ?? null,
      relationships: isBrand
        ? [{ entity_name: MOCK_BRAND, relationship: "brand", confidence: 0.7 }]
        : compName
          ? [{ entity_name: compName, relationship: "competitor", confidence: 0.7 }]
          : [],
    };
  }),
);
