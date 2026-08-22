import type { FunnelStage, PromptCategory, Sufficiency } from "@ai-search-growth-os/types";

export const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
};

export function providerLabel(key: string): string {
  return PROVIDER_LABEL[key] ?? key;
}

export const CATEGORY_LABEL: Record<PromptCategory, string> = {
  discovery: "Discovery",
  comparison: "Comparison",
  recommendation: "Recommendation",
  pricing: "Pricing",
  product: "Product",
  alternative: "Alternative",
  problem_solution: "Problem / solution",
  industry: "Industry",
};

export const FUNNEL_LABEL: Record<FunnelStage, string> = {
  awareness: "Awareness",
  consideration: "Consideration",
  decision: "Decision",
  purchase: "Purchase",
  retention: "Retention",
};

export const SUFFICIENCY_LABEL: Record<Sufficiency, string> = {
  insufficient: "Not enough data",
  low: "Low confidence",
  moderate: "Moderate confidence",
  high: "High confidence",
};

export const WINDOW_LABEL = { "7d": "7 days", "30d": "30 days", "90d": "90 days" } as const;
