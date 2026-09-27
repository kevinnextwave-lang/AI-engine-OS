"use client";

import * as React from "react";

import { fmtDateFull } from "@/lib/format";
import type { ChartEvent } from "@/lib/verify";
import { SimpleTooltip, cn } from "@ai-search-growth-os/ui";

/**
 * Accessible companion to in-chart event markers. The SVG markers stay
 * aria-hidden — this row IS the accessible representation: one button per
 * (grouped) event whose full detail opens as an inline disclosure on
 * click/Enter (works for keyboard and touch, no hover required); the
 * tooltip remains as a pointer convenience.
 */
export function ChartEventChips({ events, className }: { events: ChartEvent[]; className?: string }) {
  const [openTs, setOpenTs] = React.useState<number | null>(null);
  if (events.length === 0) return null;
  const open = events.find((e) => e.ts === openTs) ?? null;
  return (
    <div className={className}>
      <p className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
        <span className="font-medium">Changes in this window:</span>
        {events.map((e) => (
          <SimpleTooltip key={`${e.ts}-${e.label}`} label={e.detail}>
            <button
              type="button"
              aria-expanded={openTs === e.ts}
              onClick={() => setOpenTs((v) => (v === e.ts ? null : e.ts))}
              className={cn(
                "border-chart-reference/60 text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex items-center gap-1 rounded-md border border-dashed px-1.5 py-0.5 focus-visible:ring-2 focus-visible:outline-none",
                openTs === e.ts && "text-foreground bg-muted",
              )}
            >
              <span aria-hidden="true" className="bg-chart-reference size-1.5 rounded-full" />
              {fmtDateFull(new Date(e.ts).toISOString())}: {e.label}
            </button>
          </SimpleTooltip>
        ))}
      </p>
      {open && (
        <p role="status" className="text-muted-foreground mt-1 text-xs">
          {fmtDateFull(new Date(open.ts).toISOString())} — {open.detail}
        </p>
      )}
    </div>
  );
}
