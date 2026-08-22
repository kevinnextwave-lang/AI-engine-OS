/**
 * API contract → view models. Pure functions, no React, no I/O.
 * The backend already withholds numbers it cannot support; mappers only
 * reshape, they never invent a value.
 */

import type {
  PromptRow,
  VisibilityByEngine,
  VisibilityByPrompt,
  VisibilityCompetitors,
  VisibilityOverview,
  VisibilityScore,
  VisibilityTrends,
  VisibilityWindow,
} from "@ai-search-growth-os/types";

import { CATEGORY_LABEL, FUNNEL_LABEL, WINDOW_LABEL, providerLabel } from "./labels";
import type {
  ChartSeries,
  CompetitorShareRow,
  DataQualitySummary,
  EngineRow,
  PromptPerformanceRow,
  TrendWindowRow,
  VisibilityMetric,
} from "./types";

function diff(current: number | null, previous: number | null): number | null {
  if (current == null || previous == null) return null;
  return Math.round((current - previous) * 10) / 10;
}

function componentNote(score: VisibilityScore, key: string, fallback: string): string {
  return score.components.find((c) => c.key === key)?.note ?? fallback;
}

export function dataQuality(score: VisibilityScore): DataQualitySummary {
  const q = score.data_quality;
  return {
    sampleSize: q.sample_size,
    sufficiency: q.sufficiency,
    minimumSample: q.minimum_sample,
    providers: q.providers,
    prompts: q.prompts,
    start: q.date_range.start,
    end: q.date_range.end,
  };
}

/** The six primary metrics, each with previous-period change and sample size. */
export function primaryMetrics(overview: VisibilityOverview): VisibilityMetric[] {
  const cur = overview.current;
  const prev = overview.previous;
  const n = cur.data_quality.sample_size;
  const suff = cur.data_quality.sufficiency;
  const prevInsufficient = prev.data_quality.sufficiency === "insufficient";
  const changeReason = (value: number | null, previous: number | null): string | null => {
    if (value == null) return "Not enough responses in this period";
    if (previous == null) return prevInsufficient ? "Not enough responses in the previous period" : "No previous value";
    return null;
  };
  const competitive = cur.components.find((c) => c.key === "competitive_score") ?? null;
  const prevCompetitive = prev.components.find((c) => c.key === "competitive_score") ?? null;
  const m = (
    key: VisibilityMetric["key"],
    label: string,
    unit: VisibilityMetric["unit"],
    value: number | null,
    previous: number | null,
    note: string,
    lowerIsBetter = false,
    reasonOverride?: string | null,
  ): VisibilityMetric => ({
    key,
    label,
    unit,
    value,
    change: diff(value, previous),
    lowerIsBetter,
    sampleSize: n,
    sufficiency: suff,
    note,
    unavailableReason: reasonOverride ?? changeReason(value, previous),
  });
  return [
    m(
      "score",
      "AI Visibility Score",
      "score",
      cur.score,
      prev.score,
      "Weighted composite of the metrics below (25/25/15/15/10/10). Our own methodology, not an industry standard.",
      false,
      overview.reason ? overview.reason.replace(/^insufficient data/, "Not enough responses") : null,
    ),
    m("mention_rate", "Mention Rate", "percent", cur.mention_rate, prev.mention_rate, componentNote(cur, "mention_rate", "")),
    m(
      "recommendation_rate",
      "Recommendation Rate",
      "percent",
      cur.recommendation_rate,
      prev.recommendation_rate,
      componentNote(cur, "recommendation_rate", ""),
    ),
    m("citation_rate", "Citation Rate", "percent", cur.citation_rate, prev.citation_rate, componentNote(cur, "citation_rate", "")),
    m(
      "average_position",
      "Average Position",
      "position",
      cur.average_position,
      prev.average_position,
      "Mean list position where the brand appears in ranked answers. Prose mentions have no position and are excluded.",
      true,
      cur.average_position == null ? "No positioned mentions in this period" : undefined,
    ),
    m(
      "competitive_share",
      "Competitive Share",
      "score",
      competitive?.value ?? null,
      prevCompetitive?.value ?? null,
      competitive?.note ?? "Brand mention rate relative to the most-mentioned configured competitor (100 = leading).",
      false,
      competitive?.value == null
        ? overview.competitors_configured === 0
          ? "Add competitors to the project to measure this"
          : "Neither the brand nor a configured competitor was mentioned"
        : undefined,
    ),
  ];
}

export function overallSeries(trends: VisibilityTrends): ChartSeries[] {
  return [
    {
      key: "overall",
      label: "AI Visibility Score",
      points: trends.series.map((p) => ({
        date: p.start,
        end: p.end,
        value: p.score,
        sampleSize: p.sample_size,
        sufficiency: p.sufficiency,
      })),
    },
  ];
}

export function providerSeries(trends: VisibilityTrends): ChartSeries[] {
  return Object.entries(trends.series_by_provider).map(([key, points]) => ({
    key,
    label: providerLabel(key),
    points: points.map((p) => ({
      date: p.start,
      end: p.end,
      value: p.score,
      sampleSize: p.sample_size,
      sufficiency: p.sufficiency,
    })),
  }));
}

/** Mention rate per bucket — the one metric the brand and competitors share. */
export function competitorSeries(trends: VisibilityTrends, brandName: string): ChartSeries[] {
  return Object.entries(trends.series_by_competitor).map(([key, points]) => ({
    key,
    label: key === "brand" ? brandName : key,
    points: points.map((p) => ({
      date: p.start,
      end: p.end,
      value: p.mention_rate,
      sampleSize: p.sample_size,
      sufficiency: p.sufficiency,
    })),
  }));
}

export function trendWindows(trends: VisibilityTrends): TrendWindowRow[] {
  return (Object.keys(WINDOW_LABEL) as VisibilityWindow[]).map((w) => {
    const t = trends.windows[w];
    return {
      window: w,
      label: WINDOW_LABEL[w],
      current: t.current_score,
      previous: t.previous_score,
      change: t.change,
      trend: t.trend,
      reason: t.reason,
      currentSampleSize: t.current_sample_size,
      previousSampleSize: t.previous_sample_size,
    };
  });
}

export function engineRows(byEngine: VisibilityByEngine): EngineRow[] {
  return byEngine.providers
    .map((p) => ({
      provider: p.provider,
      label: providerLabel(p.provider),
      score: p.score,
      mentionRate: p.mention_rate,
      recommendationRate: p.recommendation_rate,
      citationRate: p.citation_rate,
      sampleSize: p.data_quality.sample_size,
      sufficiency: p.data_quality.sufficiency,
      models: byEngine.models
        .filter((m) => m.provider === p.provider)
        .map((m) => ({
          model: m.model,
          score: m.score,
          sampleSize: m.data_quality.sample_size,
          sufficiency: m.data_quality.sufficiency,
        })),
    }))
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

export function competitorRows(c: VisibilityCompetitors, brandName: string): CompetitorShareRow[] {
  return c.rows.map((r) => ({
    name: r.is_brand ? brandName : r.name,
    isBrand: r.is_brand,
    mentions: r.mentions,
    mentionRate: r.mention_rate,
    recommendationRate: r.recommendation_rate,
    averagePosition: r.average_position,
    sentimentScore: r.sentiment_score,
    shareOfVoice: r.share_of_voice,
  }));
}

/** Competitors mentioned more often than the brand, best first. */
export function competitorsAhead(rows: CompetitorShareRow[]): CompetitorShareRow[] {
  const brandRate = rows.find((r) => r.isBrand)?.mentionRate ?? null;
  if (brandRate == null) return [];
  return rows
    .filter((r) => !r.isBrand && r.mentionRate != null && r.mentionRate > brandRate)
    .sort((a, b) => (b.mentionRate ?? 0) - (a.mentionRate ?? 0));
}

export function promptRows(byPrompt: VisibilityByPrompt, prompts: PromptRow[]): PromptPerformanceRow[] {
  const lastRunById = new Map(prompts.map((p) => [p.id, p.last_run]));
  return byPrompt.prompts
    .map((p) => {
      const last = lastRunById.get(p.prompt_id) ?? null;
      return {
        id: p.prompt_id,
        prompt: p.text,
        category: p.category,
        categoryLabel: CATEGORY_LABEL[p.category] ?? p.category,
        funnelStage: p.funnel_stage,
        funnelStageLabel: FUNNEL_LABEL[p.funnel_stage] ?? p.funnel_stage,
        sampleSize: p.sample_size,
        sufficiency: p.sufficiency,
        mentions: p.mentions,
        mentionRate: p.mention_rate,
        recommendationRate: p.recommendation_rate,
        averagePosition: p.average_position,
        lastRun: p.last_completed_at ?? last?.completed_at ?? null,
        lastRunProvider: last?.provider_key ?? null,
      };
    })
    .sort((a, b) => (b.mentionRate ?? -1) - (a.mentionRate ?? -1) || b.sampleSize - a.sampleSize);
}
