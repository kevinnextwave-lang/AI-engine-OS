/**
 * Sample data for the AI Visibility section. Shown ONLY when no project is
 * selected or the API cannot be reached, and always behind the "Mock data"
 * badge. A selected project with too little data shows the empty state —
 * never these numbers.
 */

import type {
  PromptRow,
  VisibilityByEngine,
  VisibilityByPrompt,
  VisibilityCompetitors,
  VisibilityDataQuality,
  VisibilityOverview,
  VisibilityScore,
  VisibilitySeriesPoint,
  VisibilityTrends,
} from "@ai-search-growth-os/types";

export const MOCK_BRAND = "Acme Analytics";
const METHOD = "ai-visibility-score/v1";
const NOW = new Date("2026-08-22T12:00:00Z");

function iso(daysAgo: number): string {
  return new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();
}

function quality(sample: number, providers = 3, prompts = 24): VisibilityDataQuality {
  return {
    sample_size: sample,
    sufficiency: sample >= 50 ? "high" : sample >= 20 ? "moderate" : sample >= 5 ? "low" : "insufficient",
    providers,
    provider_keys: ["anthropic", "google", "openai"].slice(0, providers),
    models: providers,
    prompts,
    date_range: { start: iso(29), end: iso(0) },
    parser_versions: ["response-parser/v1"],
    minimum_sample: 5,
  };
}

function score(
  s: number | null,
  rates: { mention: number; rec: number; cite: number; pos: number | null; comp: number | null },
  sample: number,
  providers = 3,
  prompts = 24,
): VisibilityScore {
  return {
    method: METHOD,
    score: s,
    mention_rate: rates.mention,
    recommendation_rate: rates.rec,
    average_position: rates.pos,
    citation_rate: rates.cite,
    sentiment: { positive: Math.round(sample * 0.4), neutral: Math.round(sample * 0.15), negative: 2, mixed: 1, unknown: 0 },
    components: [
      { key: "mention_rate", value: rates.mention, weight: 25, sample, note: "responses mentioning the brand / eligible responses" },
      { key: "recommendation_rate", value: rates.rec, weight: 25, sample, note: "responses recommending the brand (moderate/strong, not negative) / eligible responses" },
      { key: "position_score", value: rates.pos == null ? null : 70, weight: 15, sample: Math.round(sample * 0.5), note: "mean of position points over mentions with a list position (1st=100 … 6+=25); unknown positions excluded" },
      { key: "citation_rate", value: rates.cite, weight: 15, sample, note: "responses citing one of the project's domains / eligible responses" },
      { key: "sentiment_score", value: 74, weight: 10, sample: Math.round(sample * 0.6), note: "positive=100, mixed/neutral=50, negative=0 over brand mentions; unknown excluded" },
      { key: "competitive_score", value: rates.comp, weight: 10, sample, note: "brand mention rate relative to the most-mentioned configured competitor (100 = leading)" },
    ],
    data_quality: quality(sample, providers, prompts),
  };
}

export const MOCK_OVERVIEW: VisibilityOverview = {
  method: METHOD,
  window: "30d",
  generated_at: iso(0),
  current: { ...score(62, { mention: 58, rec: 41, cite: 22, pos: 2.7, comp: 82 }, 72), period: { start: iso(30), end: iso(0) } },
  previous: { ...score(55, { mention: 51, rec: 36, cite: 19, pos: 3.1, comp: 70 }, 66), period: { start: iso(60), end: iso(30) } },
  change: 7,
  trend: "up",
  reason: null,
  competitors_configured: 3,
};

const OVERALL = [44, 47, 49, 51, 50, 53, 55, 56, 58, 60, 61, 62, 62];
function series(values: (number | null)[], samples: number[]): VisibilitySeriesPoint[] {
  return values.map((v, i) => {
    const start = 90 - i * 7;
    const n = samples[i] ?? 0;
    return {
      start: iso(start),
      end: iso(Math.max(start - 7, 0)),
      score: v,
      mention_rate: v == null ? null : v - 4,
      recommendation_rate: v == null ? null : v - 20,
      citation_rate: v == null ? null : Math.round(v / 3),
      sample_size: n,
      sufficiency: n >= 50 ? "high" : n >= 20 ? "moderate" : n >= 5 ? "low" : "insufficient",
    };
  });
}
const SAMPLES = [18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 12];

export const MOCK_TRENDS: VisibilityTrends = {
  method: METHOD,
  generated_at: iso(0),
  windows: {
    "7d": { current_score: 62, previous_score: 61, current_sample_size: 18, previous_sample_size: 18, sufficiency: "low", change: 1, trend: "flat", reason: null },
    "30d": { current_score: 62, previous_score: 55, current_sample_size: 72, previous_sample_size: 66, sufficiency: "high", change: 7, trend: "up", reason: null },
    "90d": { current_score: 55, previous_score: null, current_sample_size: 232, previous_sample_size: 3, sufficiency: "high", change: null, trend: "unavailable", reason: "insufficient data in the previous period" },
  },
  series: series(OVERALL, SAMPLES),
  series_by_provider: {
    openai: series(OVERALL.map((v) => v + 10), SAMPLES.map((n) => n / 3)),
    google: series(OVERALL.map((v) => v + 2), SAMPLES.map((n) => n / 3)),
    anthropic: series(OVERALL.map((v) => v - 4), SAMPLES.map((n) => n / 3)),
  },
  series_by_competitor: {
    brand: series(OVERALL.map((v) => v - 4), SAMPLES).map((p) => ({ start: p.start, end: p.end, mention_rate: p.score, sample_size: p.sample_size, sufficiency: p.sufficiency })),
    "Northwind BI": series(OVERALL.map(() => 71), SAMPLES).map((p) => ({ start: p.start, end: p.end, mention_rate: p.score, sample_size: p.sample_size, sufficiency: p.sufficiency })),
    "Contoso Insights": series(OVERALL.map((_, i) => 60 - i), SAMPLES).map((p) => ({ start: p.start, end: p.end, mention_rate: p.score, sample_size: p.sample_size, sufficiency: p.sufficiency })),
    "Fabrikam Data": series(OVERALL.map(() => 43), SAMPLES).map((p) => ({ start: p.start, end: p.end, mention_rate: p.score, sample_size: p.sample_size, sufficiency: p.sufficiency })),
  },
  minimum_sample: 5,
};

export const MOCK_BY_ENGINE: VisibilityByEngine = {
  method: METHOD,
  window: "30d",
  period: { start: iso(30), end: iso(0) },
  overall: MOCK_OVERVIEW.current,
  providers: [
    { provider: "openai", ...score(72, { mention: 67, rec: 50, cite: 29, pos: 2.3, comp: 95 }, 24, 1) },
    { provider: "google", ...score(64, { mention: 58, rec: 42, cite: 25, pos: 2.8, comp: 80 }, 24, 1) },
    { provider: "anthropic", ...score(58, { mention: 50, rec: 33, cite: 13, pos: 3.1, comp: 70 }, 24, 1) },
  ],
  models: [
    { provider: "openai", model: "gpt-4o-mini", ...score(72, { mention: 67, rec: 50, cite: 29, pos: 2.3, comp: 95 }, 24, 1) },
    { provider: "google", model: "gemini-2.0-flash", ...score(64, { mention: 58, rec: 42, cite: 25, pos: 2.8, comp: 80 }, 24, 1) },
    { provider: "anthropic", model: "claude-3-5-haiku", ...score(58, { mention: 50, rec: 33, cite: 13, pos: 3.1, comp: 70 }, 24, 1) },
  ],
};

export const MOCK_COMPETITORS: VisibilityCompetitors = {
  method: METHOD,
  window: "30d",
  period: { start: iso(30), end: iso(0) },
  competitors_configured: 3,
  competitive_score: 82,
  data_quality: quality(72),
  rows: [
    { name: "brand", is_brand: true, mentions: 42, mention_rate: 58, recommendation_rate: 41, average_position: 2.7, positioned_mentions: 30, sentiment_score: 74, sentiment: { positive: 29, neutral: 10, negative: 2, mixed: 1 }, share_of_voice: 27.3 },
    { name: "Northwind BI", is_brand: false, mentions: 51, mention_rate: 71, recommendation_rate: 55, average_position: 1.8, positioned_mentions: 40, sentiment_score: 81, sentiment: { positive: 40, neutral: 9, negative: 2 }, share_of_voice: 33.1 },
    { name: "Contoso Insights", is_brand: false, mentions: 39, mention_rate: 54, recommendation_rate: 30, average_position: 3.2, positioned_mentions: 26, sentiment_score: 60, sentiment: { positive: 20, neutral: 15, negative: 4 }, share_of_voice: 25.3 },
    { name: "Fabrikam Data", is_brand: false, mentions: 22, mention_rate: 43, recommendation_rate: 20, average_position: 4.1, positioned_mentions: 12, sentiment_score: 55, sentiment: { positive: 10, neutral: 10, negative: 2 }, share_of_voice: 14.3 },
  ],
  note: "Share of voice counts responses mentioning each name; only configured competitors are compared. Unconfigured brands never lower the score.",
};

const PROMPTS: [string, VisibilityByPrompt["prompts"][number]["category"], VisibilityByPrompt["prompts"][number]["funnel_stage"], number, number | null, number | null][] = [
  ["What are the best analytics platforms for mid-size SaaS companies?", "recommendation", "consideration", 9, 100, 2.1],
  ["Acme Analytics vs Northwind BI: which is better for product teams?", "comparison", "decision", 9, 100, 1.4],
  ["Affordable alternatives to Northwind BI", "alternative", "consideration", 9, 35, 3.5],
  ["How much does Acme Analytics cost?", "pricing", "purchase", 6, 65, null],
  ["Which BI tool has the best Snowflake integration?", "product", "consideration", 9, 20, 4.0],
  ["How do I track product adoption metrics?", "problem_solution", "awareness", 9, 10, null],
  ["Top data analytics trends for 2026", "industry", "awareness", 6, 0, null],
  ["Tools to build self-serve dashboards for customers", "discovery", "awareness", 9, 45, 2.8],
];

export const MOCK_BY_PROMPT: VisibilityByPrompt = {
  method: METHOD,
  window: "30d",
  period: { start: iso(30), end: iso(0) },
  prompts: PROMPTS.map(([text, category, funnel_stage, n, mention, pos], i) => ({
    prompt_id: `mock-prompt-${i + 1}`,
    text,
    category,
    funnel_stage,
    last_completed_at: iso(i % 3),
    sample_size: n,
    sufficiency: n >= 5 ? "low" : "insufficient",
    score: null,
    mentions: mention == null ? 0 : Math.round((n * mention) / 100),
    mention_rate: mention,
    recommendation_rate: mention == null ? null : Math.max(0, mention - 25),
    average_position: pos,
    citation_rate: mention == null ? null : Math.round(mention / 3),
    sentiment: { positive: 3, neutral: 1, negative: 0, mixed: 0, unknown: 0 },
    providers: 3,
  })),
  categories: [],
  funnel_stages: [],
};

export const MOCK_PROMPT_ROWS: PromptRow[] = MOCK_BY_PROMPT.prompts.map((p, i) => ({
  id: p.prompt_id,
  prompt_set_id: "mock-set",
  project_id: "mock-project",
  prompt: p.text,
  category: p.category,
  intent: "commercial",
  funnel_stage: p.funnel_stage,
  language: "en",
  country: null,
  priority: 3,
  status: "active",
  is_active: true,
  source: "generated",
  quality_score: 0.8,
  last_run: {
    id: `mock-run-${i}`,
    status: "completed",
    provider_key: ["openai", "google", "anthropic"][i % 3] ?? "openai",
    model_key: null,
    started_at: iso(i % 3),
    completed_at: iso(i % 3),
  },
  visibility_result: null,
  created_at: iso(40),
  updated_at: iso(0),
}));
