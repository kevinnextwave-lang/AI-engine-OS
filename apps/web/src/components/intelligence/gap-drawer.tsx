"use client";

import { ExternalLinkIcon } from "lucide-react";
import * as React from "react";

import { api } from "@/lib/api";
import { CONFIDENCE_LABEL, GAP_STATUS_LABEL, GAP_TYPE_LABEL, RECOMMENDATION, RECOMMENDATION_DISCLAIMER, SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import { fmtDateTime } from "@/components/visibility/format";
import type { CitationGap, CitationListItem, GapStatus } from "@ai-search-growth-os/types";
import { Badge, Button, NativeSelect, Progress, Separator, Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, Skeleton } from "@ai-search-growth-os/ui";

const PRIORITY_VARIANT = { high: "high", medium: "medium", low: "muted" } as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}

function summarise(items: CitationListItem[]): { prompt: string; n: number }[] {
  const m = new Map<string, number>();
  for (const c of items) m.set(c.prompt, (m.get(c.prompt) ?? 0) + 1);
  return [...m].map(([prompt, n]) => ({ prompt, n })).sort((a, b) => b.n - a.n);
}

function StatusForm({
  gap,
  live,
  busy,
  onUpdate,
}: {
  gap: CitationGap;
  live: boolean;
  busy: boolean;
  onUpdate: (gapId: string, body: { status?: GapStatus; note?: string | null }) => Promise<void>;
}) {
  const [status, setStatus] = React.useState<GapStatus>(gap.status);
  const [note, setNote] = React.useState(gap.note ?? "");
  const unchanged = status === gap.status && (note.trim() || null) === (gap.note ?? null);
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void onUpdate(gap.id, { status, note: note.trim() || null });
      }}
    >
      <div className="grid grid-cols-[10rem_1fr] gap-2">
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as GapStatus)} disabled={!live}>
          {(Object.keys(GAP_STATUS_LABEL) as GapStatus[]).map((s) => (
            <option key={s} value={s}>
              {GAP_STATUS_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
        <input
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note (optional)"
          maxLength={2000}
          disabled={!live}
        />
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={!live || busy || unchanged}>
          {busy ? "Saving…" : "Update status"}
        </Button>
        <span className="text-muted-foreground text-xs">Analysed {fmtDateTime(gap.analyzed_at)}</span>
      </div>
    </form>
  );
}

function Bar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  return (
    <div className="grid grid-cols-[9rem_1fr_3rem] items-center gap-2 text-sm">
      <span className="truncate">{label}</span>
      <Progress value={max ? (100 * value) / max : 0} indicatorClassName={tone} aria-label={`${label}: ${value}`} />
      <span className="text-right tabular-nums">{value}</span>
    </div>
  );
}

export function GapDrawer({
  gap,
  brandName,
  projectId,
  live,
  mockCitations,
  busy,
  onUpdate,
  onClose,
}: {
  gap: CitationGap | null;
  brandName: string;
  projectId: string | null;
  live: boolean;
  mockCitations: CitationListItem[];
  busy: boolean;
  onUpdate: (gapId: string, body: { status?: GapStatus; note?: string | null }) => Promise<void>;
  onClose: () => void;
}) {
  const [prompts, setPrompts] = React.useState<{ id: string; list: { prompt: string; n: number }[] | null } | null>(null);
  const id = gap?.id ?? null;
  const domainId = gap?.source_domain_id ?? null;
  const mockList = React.useMemo(
    () => (!gap || (live && projectId) ? null : summarise(mockCitations.filter((c) => c.source_domain_id === gap.source_domain_id))),
    [gap, live, projectId, mockCitations],
  );

  React.useEffect(() => {
    if (!id || !domainId || !live || !projectId) return;
    let cancelled = false;
    api.citations
      .list(projectId, { source_domain_id: domainId, limit: 500 })
      .then((r) => !cancelled && setPrompts({ id, list: summarise(r.items) }))
      .catch(() => !cancelled && setPrompts({ id, list: [] }));
    return () => {
      cancelled = true;
    };
  }, [id, domainId, live, projectId]);

  const list = mockList ?? (prompts?.id === id ? prompts.list : null);
  const max = gap ? Math.max(gap.brand_citations, ...Object.values(gap.competitors), 1) : 1;
  const comps = gap ? Object.entries(gap.competitors).sort((a, b) => b[1] - a[1]) : [];
  const components = gap?.evidence.components ?? {};

  return (
    <Sheet open={gap !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        {gap && (
          <>
            <SheetHeader className="pr-10">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={PRIORITY_VARIANT[gap.priority]} className="uppercase">
                  {gap.priority} opportunity
                </Badge>
                <Badge variant="secondary">{GAP_TYPE_LABEL[gap.gap_type]}</Badge>
                <Badge variant="outline">{SOURCE_TYPE_LABEL[gap.source_type]}</Badge>
              </div>
              <SheetTitle className="text-lg">{gap.display_name}</SheetTitle>
              <SheetDescription>{gap.explanation}</SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-5 px-4 pb-6">
              <Section title="Opportunity">
                <div className="flex items-baseline gap-3">
                  <span className="text-4xl font-semibold tabular-nums">{Math.round(gap.opportunity_score)}</span>
                  <span className="text-muted-foreground text-sm">/100 Citation Opportunity Score · {CONFIDENCE_LABEL[gap.confidence]}</span>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                  {Object.entries(components).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt>
                      <dd className="tabular-nums">
                        {Math.round(v.value)} <span className="text-muted-foreground">× {v.weight}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              </Section>
              <Separator />
              <Section title="Competitor advantage">
                <div className="flex flex-col gap-1.5">
                  {comps.length === 0 && <p className="text-muted-foreground text-sm">No configured competitor is cited from this source.</p>}
                  {comps.map(([name, n]) => (
                    <Bar key={name} label={name} value={n} max={max} tone="bg-amber-500" />
                  ))}
                </div>
              </Section>
              <Section title="Your presence">
                <Bar label={brandName} value={gap.brand_citations} max={max} tone="bg-primary" />
                <p className="text-muted-foreground text-xs">
                  {gap.brand_citations} brand-related citation{gap.brand_citations === 1 ? "" : "s"} out of {gap.relevant_response_count} relevant AI responses.
                </p>
              </Section>
              <Section title="Evidence">
                {gap.evidence.top_pages && gap.evidence.top_pages.length > 0 && (
                  <ul className="flex flex-col gap-1 text-sm">
                    {gap.evidence.top_pages.map((p) => (
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
                <p className="text-muted-foreground mt-1 text-xs font-medium">Prompts where the source appeared</p>
                {list === null ? (
                  <Skeleton className="h-12 w-full" />
                ) : list.length === 0 ? (
                  <p className="text-muted-foreground text-sm">No stored citations in the current window.</p>
                ) : (
                  <ul className="flex flex-col gap-1 text-sm">
                    {list.slice(0, 10).map((p) => (
                      <li key={p.prompt} className="flex justify-between gap-2">
                        <span className="truncate">{p.prompt}</span>
                        <span className="text-muted-foreground shrink-0 tabular-nums">{p.n}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
              <Section title="Recommendation">
                <p className="text-sm leading-relaxed">{RECOMMENDATION[gap.gap_type]}</p>
                <p className="text-muted-foreground text-xs">{RECOMMENDATION_DISCLAIMER}</p>
                <p className="text-muted-foreground text-xs">A citation from this source does not guarantee better AI visibility; it changes what AI engines can find and attribute.</p>
              </Section>
              <Separator />
              <Section title="Status">
                <StatusForm key={gap.id + gap.status + (gap.note ?? "")} gap={gap} live={live} busy={busy} onUpdate={onUpdate} />
              </Section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
