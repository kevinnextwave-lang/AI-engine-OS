"use client";

import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { TopSourceBar } from "@/lib/intelligence/types";
import { Card, CardContent, CardHeader, CardTitle, Skeleton } from "@ai-search-growth-os/ui";

/** Horizontal bars of the most-cited domains; brand vs competitor vs other shares stacked. */
export function SourceChart({ items, loading, onSelect }: { items: TopSourceBar[]; loading?: boolean; onSelect?: (sourceDomainId: string) => void }) {
  const max = Math.max(1, ...items.map((i) => i.citations));
  return (
    <Card className="gap-3 py-5">
      <CardHeader className="px-5">
        <CardTitle className="text-base">Top cited sources</CardTitle>
        <p className="text-muted-foreground text-xs">Citations in parsed AI responses, by source domain. Shaded segments: citations related to your brand (dark) and to competitors (amber).</p>
      </CardHeader>
      <CardContent className="px-5">
        {loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground text-sm">No sources cited in this period.</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {items.map((s) => {
              const brandPct = (100 * s.brandCitations) / max;
              const compPct = (100 * s.competitorCitations) / max;
              const otherPct = (100 * Math.max(0, s.citations - s.brandCitations - s.competitorCitations)) / max;
              return (
                <li key={s.sourceDomainId} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-3 text-sm">
                  <button type="button" className="truncate text-left hover:underline" title={`${s.domain} · ${SOURCE_TYPE_LABEL[s.sourceType]}`} onClick={() => onSelect?.(s.sourceDomainId)}>
                    {s.domain}
                  </button>
                  <div className="bg-muted flex h-4 overflow-hidden rounded" role="img" aria-label={`${s.domain}: ${s.citations} citations`}>
                    <span className="bg-primary h-full" style={{ width: `${brandPct}%` }} />
                    <span className="h-full bg-amber-500" style={{ width: `${compPct}%` }} />
                    <span className="bg-muted-foreground/40 h-full" style={{ width: `${otherPct}%` }} />
                  </div>
                  <span className="text-right font-medium tabular-nums">{s.citations}</span>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
