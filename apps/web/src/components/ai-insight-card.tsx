"use client";

import Link from "next/link";
import * as React from "react";

import type { InsightModel } from "@/lib/ai-insights";
import { AiActionList, AiInsight, Button } from "@ai-search-growth-os/ui";

/**
 * App-level renderer for the shared AiInsight pattern: takes an InsightModel
 * (built by lib/ai-insights.ts from stored data) plus a CTA target. Renders
 * nothing for a null insight, so pages can pass builders' results straight in.
 */
export function AiInsightCard({
  insight,
  href,
  onCta,
  className,
}: {
  insight: InsightModel | null;
  /** Link CTA (navigation) — or use onCta for in-page actions. */
  href?: string;
  onCta?: () => void;
  className?: string;
}) {
  if (!insight) return null;
  const cta = href ? (
    <Button asChild size="sm" variant="outline">
      <Link href={href}>{insight.ctaLabel}</Link>
    </Button>
  ) : onCta ? (
    <Button size="sm" variant="outline" onClick={onCta}>
      {insight.ctaLabel}
    </Button>
  ) : undefined;
  return (
    <AiInsight
      headline={insight.headline}
      whyItMatters={insight.whyItMatters}
      action={
        insight.actions.length === 1 ? (
          <p>{insight.actions[0]}</p>
        ) : (
          <AiActionList items={insight.actions} />
        )
      }
      evidence={insight.evidence}
      source={insight.source}
      cta={cta}
      className={className}
    />
  );
}
