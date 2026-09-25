import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { cn } from "@ai-search-growth-os/ui";

/**
 * The citation-intelligence object chain, shown on every page in this area
 * so the information architecture is always visible:
 *
 *   Prompt → AI response → Claims · Citations → Source
 *
 * The current page's object is highlighted; every other stage links to its
 * page. One quiet line — orientation, not decoration.
 */

const STAGES: Array<{ key: string; label: string; href: string }> = [
  { key: "prompt", label: "Prompt", href: "/app/ai-visibility/prompts" },
  { key: "response", label: "AI response", href: "/app/ai-intelligence/ai-responses" },
  { key: "claim", label: "Claims", href: "/app/ai-intelligence/claims" },
  { key: "citation", label: "Citations", href: "/app/ai-intelligence/citations" },
  { key: "source", label: "Source", href: "/app/ai-intelligence/sources" },
];

export function ChainStrip({ current }: { current: "prompt" | "response" | "claim" | "citation" | "source" }) {
  return (
    <nav aria-label="How these objects relate" className="text-muted-foreground mb-4 flex flex-wrap items-center gap-1 text-xs">
      <span className="mr-1">Each answer&apos;s trail:</span>
      {STAGES.map((s, i) => (
        <React.Fragment key={s.key}>
          {i > 0 && <ChevronRightIcon className="size-3 opacity-60" aria-hidden="true" />}
          {s.key === current ? (
            <span className="bg-primary/10 text-primary rounded px-1.5 py-0.5 font-medium" aria-current="page">
              {s.label}
            </span>
          ) : (
            <Link href={s.href} className={cn("hover:text-foreground rounded px-1.5 py-0.5 underline-offset-4 hover:underline")}>
              {s.label}
            </Link>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}
