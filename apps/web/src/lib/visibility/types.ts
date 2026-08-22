/**
 * View models for the AI Visibility section. Derived from API contract types
 * (packages/types) by ./mappers.ts; components render them and never compute.
 *
 * Every number here is a *measured AI-response visibility metric* computed by
 * the backend's AI Visibility Score methodology (docs/ai-visibility-score.md).
 * `null` always means "not enough data", never zero.
 */

import type {
  PromptCategory,
  FunnelStage,
  Sufficiency,
  TrendDirection,
  VisibilityWindow,
} from "@ai-search-growth-os/types";

export type { DataSource } from "@/lib/geo/types";
export type { Sufficiency, TrendDirection, VisibilityWindow };

export type MetricUnit = "score" | "percent" | "position";

export interface VisibilityMetric {
  key: "score" | "mention_rate" | "recommendation_rate" | "citation_rate" | "average_position" | "competitive_share";
  label: string;
  unit: MetricUnit;
  value: number | null;
  /** Previous-period change in the metric's own unit; null when unavailable. */
  change: number | null;
  /** For positions, lower is better. */
  lowerIsBetter: boolean;
  sampleSize: number;
  sufficiency: Sufficiency;
  /** One-line derivation shown as a tooltip. */
  note: string;
  /** Why change is unavailable (when it is). */
  unavailableReason: string | null;
}

export interface DataQualitySummary {
  sampleSize: number;
  sufficiency: Sufficiency;
  minimumSample: number;
  providers: number;
  prompts: number;
  start: string | null;
  end: string | null;
}

export interface ChartPoint {
  /** Bucket start (ISO). */
  date: string;
  /** Bucket end (ISO). */
  end: string;
  value: number | null;
  sampleSize: number;
  sufficiency: Sufficiency;
}

export interface ChartSeries {
  key: string;
  label: string;
  points: ChartPoint[];
}

export type ChartMode = "overall" | "provider" | "competitor";

export interface EngineRow {
  provider: string;
  label: string;
  score: number | null;
  mentionRate: number | null;
  recommendationRate: number | null;
  citationRate: number | null;
  sampleSize: number;
  sufficiency: Sufficiency;
  models: { model: string; score: number | null; sampleSize: number; sufficiency: Sufficiency }[];
}

export interface CompetitorShareRow {
  name: string;
  isBrand: boolean;
  mentions: number;
  mentionRate: number | null;
  recommendationRate: number | null;
  averagePosition: number | null;
  sentimentScore: number | null;
  shareOfVoice: number | null;
}

export interface PromptPerformanceRow {
  id: string;
  prompt: string;
  category: PromptCategory;
  categoryLabel: string;
  funnelStage: FunnelStage;
  funnelStageLabel: string;
  sampleSize: number;
  sufficiency: Sufficiency;
  mentions: number;
  mentionRate: number | null;
  recommendationRate: number | null;
  averagePosition: number | null;
  /** ISO timestamp of the newest completed run, when known. */
  lastRun: string | null;
  lastRunProvider: string | null;
}

export interface TrendWindowRow {
  window: VisibilityWindow;
  label: string;
  current: number | null;
  previous: number | null;
  change: number | null;
  trend: TrendDirection;
  reason: string | null;
  currentSampleSize: number;
  previousSampleSize: number;
}
