"use client";

/**
 * The visibility pipeline: makes the relationship between the product's core
 * objects visually explicit and clickable —
 *
 *   Prompts → AI responses → Mentions → Citations
 *
 * Every number is a real measured count from the selected window; the last
 * stage shows the measured citation rate (share of responses citing the
 * brand's own site). Each stage links to the page where that object lives,
 * so "why is my visibility low?" walks left to right into the answer.
 */

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Card, CardContent, Skeleton, cn } from "@ai-search-growth-os/ui";

interface Stage {
  value: string;
  label: string;
  sub: string;
  href: string;
}

export function VisibilityFunnel({
  brandName,
  promptsTracked,
  enginesMonitored,
  enginesAnswering,
  responses,
  mentionResponses,
  citationRate,
  windowLabel,
  loading,
}: {
  brandName: string;
  promptsTracked: number;
  /** Providers the server is configured to query. */
  enginesMonitored: number;
  /** Engines that returned parsed responses in this window. */
  enginesAnswering: number;
  responses: number;
  /** Responses that mention the brand (sum of per-prompt mention counts). */
  mentionResponses: number;
  /** Measured share of responses citing the brand's own site; null if unmeasured. */
  citationRate: number | null;
  windowLabel: string;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card className="mb-6 py-4">
        <CardContent className="flex flex-col gap-3 px-4">
          <Skeleton className="h-4 w-56" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }
  // Without responses the page-level invitation state explains what to do.
  if (responses === 0) return null;

  const stages: Stage[] = [
    {
      value: String(promptsTracked),
      label: promptsTracked === 1 ? "Prompt tracked" : "Prompts tracked",
      sub: "Real buyer questions asked to AI engines",
      href: "/app/ai-visibility/prompts",
    },
    {
      value: String(responses),
      label: responses === 1 ? "AI response analyzed" : "AI responses analyzed",
      sub:
        enginesMonitored >= enginesAnswering && enginesMonitored > 0
          ? `From ${enginesAnswering} of ${enginesMonitored} monitored engine${enginesMonitored === 1 ? "" : "s"}`
          : `From ${enginesAnswering} AI engine${enginesAnswering === 1 ? "" : "s"}`,
      href: "/app/ai-intelligence/ai-responses",
    },
    {
      value: String(mentionResponses),
      label: mentionResponses === 1 ? "Response mentions you" : "Responses mention you",
      sub: `Answers naming ${brandName}`,
      href: "/app/ai-visibility/prompts?filter=mentioned",
    },
    {
      value: citationRate == null ? "–" : `${Math.round(citationRate)}%`,
      label: "Cite your site",
      sub: "Share of responses citing your own domain",
      href: "/app/ai-intelligence/citations",
    },
  ];

  return (
    <Card className="mb-6 py-4">
      <CardContent className="px-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium">How your visibility is measured</p>
          <p className="text-muted-foreground text-xs">{windowLabel}</p>
        </div>
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {stages.map((stage, i) => (
            <li key={stage.href} className="relative">
              <Link
                href={stage.href}
                className={cn(
                  "bg-background/60 hover:border-primary/40 hover:bg-primary/[0.03] group flex h-full flex-col gap-0.5 rounded-lg border p-3 transition-colors",
                )}
              >
                <span className="text-2xl font-semibold tabular-nums">{stage.value}</span>
                <span className="group-hover:text-primary text-sm font-medium transition-colors">{stage.label}</span>
                <span className="text-muted-foreground text-xs leading-snug">{stage.sub}</span>
              </Link>
              {i < stages.length - 1 && (
                <ChevronRightIcon
                  className="text-muted-foreground/50 absolute top-1/2 -right-[13px] z-10 hidden size-4 -translate-y-1/2 lg:block"
                  aria-hidden="true"
                />
              )}
            </li>
          ))}
        </ol>
        <p className="text-muted-foreground mt-2 text-xs">
          Each step drills into the underlying data: prompts → the answers engines gave → where you were named →
          what they cited.
        </p>
      </CardContent>
    </Card>
  );
}
