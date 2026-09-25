import * as React from "react";
import { SparklesIcon } from "lucide-react";

import { cn } from "./utils";

/**
 * THE "AI Recommendation" pattern. One anatomy everywhere the product turns
 * measured data into advice:
 *
 *   ✦ AI RECOMMENDATION
 *   "What I found" — one plain statement of a measured fact.
 *   Why this matters — mechanism, in cautious language.
 *   Recommended action — what to do about it (text or a short ordered list).
 *   Evidence — the exact numbers the statement rests on.
 *   ─────────────────────────────
 *   provenance line                                  [CTA]
 *
 * Content rules (enforced by convention, reviewed in code review):
 * - `headline` states only what was measured; `evidence` carries the numbers
 *   backing it. Nothing is projected or estimated.
 * - `whyItMatters` explains mechanism ("makes X easier/harder"), never
 *   outcomes ("will increase traffic by N%").
 * - `source` names the analysis and its age, so provenance is always visible.
 */

export interface AiEvidenceFact {
  label: React.ReactNode;
  value: React.ReactNode;
}

function AiInsight({
  title = "AI Recommendation",
  headline,
  whyItMatters,
  action,
  evidence,
  source,
  cta,
  className,
}: {
  /** Eyebrow label; keep the default unless the surface truly differs. */
  title?: React.ReactNode;
  /** What I found — one plain statement of measured fact. */
  headline: React.ReactNode;
  /** Why it matters — mechanism, cautious language, no outcome claims. */
  whyItMatters?: React.ReactNode;
  /** Recommended action — a sentence, or a short ordered list. */
  action?: React.ReactNode;
  /** The numbers behind the headline. */
  evidence?: AiEvidenceFact[] | React.ReactNode;
  /** Provenance: which analysis produced this, and when. */
  source?: React.ReactNode;
  cta?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="ai-insight"
      className={cn("border-primary/20 bg-primary/[0.03] flex flex-col gap-3 rounded-xl border p-4", className)}
    >
      <div className="text-primary flex items-center gap-1.5">
        <SparklesIcon className="size-3.5" aria-hidden="true" />
        <span className="text-[11px] font-medium tracking-wider uppercase">{title}</span>
      </div>
      <p className="text-sm leading-snug font-medium">{headline}</p>
      {whyItMatters && (
        <div>
          <p className="text-muted-foreground text-xs font-semibold">Why this matters</p>
          <p className="text-muted-foreground mt-0.5 text-sm leading-relaxed">{whyItMatters}</p>
        </div>
      )}
      {action && (
        <div>
          <p className="text-muted-foreground text-xs font-semibold">Recommended action</p>
          <div className="mt-0.5 text-sm leading-relaxed">{action}</div>
        </div>
      )}
      {evidence != null &&
        (Array.isArray(evidence) ? (
          evidence.length > 0 && (
            <div>
              <p className="text-muted-foreground text-xs font-semibold">Evidence</p>
              <dl className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
                {evidence.map((fact, i) => (
                  <div key={i} className="flex items-baseline gap-1.5 text-xs">
                    <dt className="text-muted-foreground">{fact.label}</dt>
                    <dd className="font-medium tabular-nums">{fact.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )
        ) : (
          <div>
            <p className="text-muted-foreground text-xs font-semibold">Evidence</p>
            <div className="mt-1">{evidence}</div>
          </div>
        ))}
      {(source || cta) && (
        <div className="border-primary/10 mt-1 flex flex-wrap items-center justify-between gap-2 border-t pt-2.5">
          <p className="text-muted-foreground text-xs">{source}</p>
          {cta}
        </div>
      )}
    </div>
  );
}

/** Ordered action list for AiInsight's `action` slot. */
function AiActionList({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="flex list-decimal flex-col gap-1 pl-4 marker:text-xs marker:font-medium">
      {items.map((item, i) => (
        <li key={i} className="pl-0.5">
          {item}
        </li>
      ))}
    </ol>
  );
}

export { AiActionList, AiInsight };
