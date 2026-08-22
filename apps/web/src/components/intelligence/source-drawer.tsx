"use client";

import { ExternalLinkIcon } from "lucide-react";
import * as React from "react";

import { fmtDate } from "@/components/visibility/format";
import { ErrorState } from "@/components/visibility/states";
import { api } from "@/lib/api";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import { sourceDetail } from "@/lib/intelligence/mappers";
import type { SourceDetail, SourceRow } from "@/lib/intelligence/types";
import type { CitationListItem } from "@ai-search-growth-os/types";
import { Badge, Separator, Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, Skeleton } from "@ai-search-growth-os/ui";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}

function CountList({ items, empty }: { items: { name: string; citations: number }[]; empty: string }) {
  if (items.length === 0) return <p className="text-muted-foreground text-sm">{empty}</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((i) => (
        <li key={i.name}>
          <Badge variant="outline">
            {i.name} · {i.citations}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

/** Weekly citation bars. */
export function TrendBars({ trend }: { trend: { weekStart: string; citations: number }[] }) {
  if (trend.length === 0) return <p className="text-muted-foreground text-sm">No dated citations.</p>;
  const max = Math.max(1, ...trend.map((t) => t.citations));
  return (
    <div className="flex items-end gap-1" role="img" aria-label="Citations per week">
      {trend.map((t) => (
        <div key={t.weekStart} className="flex flex-1 flex-col items-center justify-end gap-1" title={`Week of ${fmtDate(t.weekStart)}: ${t.citations}`}>
          <span className="text-muted-foreground text-[10px] tabular-nums">{t.citations}</span>
          <div className="bg-primary/70 w-full rounded-t" style={{ height: `${Math.max(3, Math.round((72 * t.citations) / max))}px` }} />
          <span className="text-muted-foreground text-[10px]">{fmtDate(t.weekStart)}</span>
        </div>
      ))}
    </div>
  );
}

export function SourceDrawer({
  row,
  projectId,
  range,
  live,
  mockCitations,
  onClose,
}: {
  row: SourceRow | null;
  projectId: string | null;
  range: { start: string; end: string };
  live: boolean;
  mockCitations: CitationListItem[];
  onClose: () => void;
}) {
  const [state, setState] = React.useState<{ id: string; detail: SourceDetail | null; error: string | null } | null>(null);
  const [version, setVersion] = React.useState(0);
  const id = row?.sourceDomainId ?? null;

  const mockDetail = React.useMemo(() => {
    if (!row || !id || (live && projectId)) return null;
    const cites = mockCitations.filter((c) => c.source_domain_id === id);
    return sourceDetail(row, cites, cites.length);
  }, [row, id, live, projectId, mockCitations]);

  React.useEffect(() => {
    if (!row || !id || !live || !projectId) return;
    let cancelled = false;
    api.citations
      .list(projectId, { ...range, source_domain_id: id, limit: 500 })
      .then((r) => !cancelled && setState({ id, detail: sourceDetail(row, r.items, r.total), error: null }))
      .catch((err: unknown) => !cancelled && setState({ id, detail: null, error: err instanceof Error ? err.message : "Request failed" }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, live, projectId, range.start, range.end, version]);

  const detail = mockDetail ?? (state?.id === id ? state.detail : null);
  const error = mockDetail ? null : state?.id === id ? state.error : null;

  return (
    <Sheet open={row !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        {row && (
          <>
            <SheetHeader className="pr-10">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{SOURCE_TYPE_LABEL[row.sourceType]}</Badge>
                {row.gap && <Badge variant="outline">Opportunity {Math.round(row.gap.opportunity_score)}</Badge>}
              </div>
              <SheetTitle className="text-lg">{row.domain}</SheetTitle>
              <SheetDescription>
                {row.citations} citations in {row.responses} AI responses across {row.prompts} prompt{row.prompts === 1 ? "" : "s"}
                {row.firstCitedAt && ` · ${fmtDate(row.firstCitedAt)} – ${fmtDate(row.lastCitedAt)}`}
              </SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-5 px-4 pb-6">
              {error ? (
                <ErrorState message={error} onRetry={() => setVersion((v) => v + 1)} />
              ) : !detail ? (
                <div className="flex flex-col gap-3">
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : (
                <>
                  <Section title="Citation trend">
                    <TrendBars trend={detail.trend} />
                    {detail.citationsLoaded < detail.citationsTotal && (
                      <p className="text-muted-foreground text-xs">Showing the {detail.citationsLoaded} most recent of {detail.citationsTotal} citations.</p>
                    )}
                  </Section>
                  <Separator />
                  <Section title="Pages cited">
                    {detail.pages.length === 0 ? (
                      <p className="text-muted-foreground text-sm">Only domain-level references, no page URLs.</p>
                    ) : (
                      <ul className="flex flex-col gap-1 text-sm">
                        {detail.pages.slice(0, 15).map((p) => (
                          <li key={p.url} className="flex items-center justify-between gap-2">
                            <a href={p.url} target="_blank" rel="noreferrer" className="text-primary inline-flex min-w-0 items-center gap-1 truncate underline-offset-4 hover:underline">
                              <span className="truncate">{p.url}</span>
                              <ExternalLinkIcon className="size-3 shrink-0" aria-hidden="true" />
                            </a>
                            <span className="text-muted-foreground shrink-0 tabular-nums">{p.citations}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Section>
                  <Section title="AI engines">
                    <CountList items={detail.engines.map((e) => ({ name: `${e.label}${e.model ? ` · ${e.model}` : ""}`, citations: e.citations }))} empty="No engine recorded." />
                  </Section>
                  <Section title="Brands observed">
                    <CountList items={detail.brands} empty="Your brand was not associated with this source's citations." />
                  </Section>
                  <Section title="Competitors observed">
                    <CountList items={detail.competitors} empty="No configured competitor was associated with this source's citations." />
                  </Section>
                  <Section title="Prompts where it appeared">
                    <ul className="flex flex-col gap-1 text-sm">
                      {detail.prompts.slice(0, 10).map((p) => (
                        <li key={p.promptId} className="flex justify-between gap-2">
                          <span className="truncate">{p.prompt}</span>
                          <span className="text-muted-foreground shrink-0 tabular-nums">{p.citations}</span>
                        </li>
                      ))}
                    </ul>
                  </Section>
                </>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
