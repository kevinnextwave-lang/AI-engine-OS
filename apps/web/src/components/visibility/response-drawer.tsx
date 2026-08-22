"use client";

import { ExternalLinkIcon } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/visibility/states";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import { highlight, type HighlightKind, type Marker, type Segment } from "@/lib/visibility/highlight";
import { providerLabel } from "@/lib/visibility/labels";
import type { PromptPerformanceRow } from "@/lib/visibility/types";
import type { PromptRun, ResponseIntelligence } from "@ai-search-growth-os/types";
import {
  Badge,
  NativeSelect,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  cn,
} from "@ai-search-growth-os/ui";

const MARK_CLASS: Record<HighlightKind, string> = {
  brand: "bg-primary/20 text-foreground rounded px-0.5 ring-1 ring-primary/40",
  competitor: "bg-amber-500/20 rounded px-0.5 ring-1 ring-amber-500/40",
  citation: "bg-sky-500/20 rounded px-0.5 ring-1 ring-sky-500/40",
  claim: "underline decoration-dotted decoration-violet-500 underline-offset-4",
};

const LEGEND: { kind: HighlightKind; label: string }[] = [
  { kind: "brand", label: "Your brand" },
  { kind: "competitor", label: "Competitor" },
  { kind: "citation", label: "Citation" },
  { kind: "claim", label: "Claim" },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.kind ? (
          <mark key={i} className={cn("bg-transparent", MARK_CLASS[s.kind])} title={s.title}>
            {s.children ? <Segments segments={s.children} /> : s.text}
          </mark>
        ) : (
          <React.Fragment key={i}>{s.text}</React.Fragment>
        ),
      )}
    </>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-sm font-medium capitalize">{value}</dd>
    </div>
  );
}

function markersFor(intel: ResponseIntelligence, brandName: string): Marker[] {
  const brand: Marker[] = intel.mentions.map((m) => ({
    kind: "brand",
    text: m.mention_text || m.brand_name,
    title: `${brandName} · ${m.sentiment} · ${m.recommendation_strength}`,
  }));
  if (brand.length === 0) brand.push({ kind: "brand", text: brandName });
  const competitors: Marker[] = intel.competitor_mentions.map((m) => ({
    kind: "competitor",
    text: m.mention_text || m.brand_name,
    title: `Competitor: ${m.brand_name}`,
  }));
  const citations: Marker[] = intel.citations.flatMap((c) =>
    [c.url, c.anchor_text, c.domain].filter((t): t is string => !!t).map((text) => ({ kind: "citation" as const, text, title: c.url ?? c.domain ?? "Citation" })),
  );
  const claims: Marker[] = intel.claims
    .filter((c) => c.context)
    .map((c) => ({ kind: "claim", text: c.context, title: `${c.subject} ${c.predicate} ${c.object}` }));
  return [...brand, ...competitors, ...citations, ...claims];
}

interface State {
  runs: PromptRun[] | null;
  error: string | null;
}

export function ResponseDrawer({
  prompt,
  brandName,
  live,
  onClose,
}: {
  prompt: PromptPerformanceRow | null;
  brandName: string;
  /** False when sample data is shown — there is no history to fetch. */
  live: boolean;
  onClose: () => void;
}) {
  const [state, setState] = React.useState<State & { promptId: string } | null>(null);
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null);
  const [intel, setIntel] = React.useState<{ runId: string; data: ResponseIntelligence | null; error: string | null } | null>(null);
  const [version, setVersion] = React.useState(0);

  const promptId = prompt?.id ?? null;
  React.useEffect(() => {
    if (!promptId || !live) return;
    let cancelled = false;
    api.prompts
      .runs(promptId)
      .then((r) => !cancelled && setState({ promptId, runs: r.items, error: null }))
      .catch((err: unknown) => !cancelled && setState({ promptId, runs: null, error: err instanceof Error ? err.message : "Request failed" }));
    return () => {
      cancelled = true;
    };
  }, [promptId, live, version]);

  const runs = state?.promptId === promptId ? state.runs : null;
  const runsError = state?.promptId === promptId ? state.error : null;
  const completed = React.useMemo(() => (runs ?? []).filter((r) => r.status === "completed" && r.response), [runs]);
  const run = completed.find((r) => r.id === selectedRunId) ?? completed[0] ?? null;

  const runId = run?.id ?? null;
  React.useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    api.intelligence
      .forRun(runId)
      .then((d) => !cancelled && setIntel({ runId, data: d, error: null }))
      .catch((err: unknown) => !cancelled && setIntel({ runId, data: null, error: err instanceof Error ? err.message : "Request failed" }));
    return () => {
      cancelled = true;
    };
  }, [runId, version]);

  const analysis = intel?.runId === runId ? intel : null;
  const segments = React.useMemo(() => {
    if (!run?.response) return [];
    return highlight(run.response.response_text, analysis?.data ? markersFor(analysis.data, brandName) : [{ kind: "brand", text: brandName }]);
  }, [run, analysis, brandName]);

  const summary = analysis?.data;
  const brandMention = summary?.mentions[0] ?? null;
  const loadingRuns = live && runs === null && runsError === null;

  return (
    <Sheet
      open={prompt !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
          setSelectedRunId(null);
        }
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        {prompt && (
          <>
            <SheetHeader className="pr-10">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{prompt.categoryLabel}</Badge>
                <Badge variant="outline">{prompt.funnelStageLabel}</Badge>
              </div>
              <SheetTitle className="text-lg leading-snug">{prompt.prompt}</SheetTitle>
              <SheetDescription>
                Response history · {prompt.sampleSize} parsed response{prompt.sampleSize === 1 ? "" : "s"} in the selected period
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-5 px-4 pb-6">
              {!live ? (
                <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                  Sample data has no stored AI responses. Select a project with completed prompt runs to read the actual answers.
                </p>
              ) : runsError ? (
                <ErrorState message={runsError} onRetry={() => setVersion((v) => v + 1)} />
              ) : loadingRuns ? (
                <div className="flex flex-col gap-3">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-40 w-full" />
                </div>
              ) : completed.length === 0 ? (
                <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                  No completed run has a stored response for this prompt yet.
                  {runs && runs.length > 0 && ` ${runs.length} run${runs.length === 1 ? " is" : "s are"} queued, running or failed.`}
                </p>
              ) : (
                <>
                  <Section title="Run">
                    <NativeSelect aria-label="Run" value={run?.id ?? ""} onChange={(e) => setSelectedRunId(e.target.value)}>
                      {completed.map((r) => (
                        <option key={r.id} value={r.id}>
                          {fmtDateTime(r.completed_at)} · {providerLabel(r.provider_key ?? "?")} · {r.model_key ?? "default model"}
                        </option>
                      ))}
                    </NativeSelect>
                    {run && (
                      <dl className="mt-2 grid grid-cols-3 gap-3">
                        <Fact label="Provider" value={providerLabel(run.provider_key ?? "?")} />
                        <Fact label="Model" value={<span className="font-mono text-xs normal-case">{run.model_key ?? "–"}</span>} />
                        <Fact label="Timestamp" value={<span className="normal-case">{fmtDateTime(run.completed_at)}</span>} />
                      </dl>
                    )}
                  </Section>

                  <Separator />

                  <Section title="Analysis">
                    {analysis?.error ? (
                      <ErrorState message={analysis.error} onRetry={() => setVersion((v) => v + 1)} />
                    ) : !analysis ? (
                      <Skeleton className="h-16 w-full" />
                    ) : !summary?.parser_version ? (
                      <p className="text-muted-foreground text-sm">This response has not been parsed yet.</p>
                    ) : (
                      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                        <Fact label="Brand mention" value={summary.mentions.length > 0 ? "Yes" : "No"} />
                        <Fact label="Sentiment" value={brandMention?.sentiment ?? "–"} />
                        <Fact label="Recommendation" value={brandMention?.recommendation_strength ?? "–"} />
                        <Fact label="Position" value={brandMention?.position != null ? `#${brandMention.position}` : "–"} />
                        <Fact label="Citations" value={String(summary.citations.length)} />
                      </dl>
                    )}
                  </Section>

                  <Section title="AI response">
                    <div className="flex flex-wrap gap-3 text-xs">
                      {LEGEND.map((l) => (
                        <span key={l.kind} className="inline-flex items-center gap-1.5">
                          <span className={cn("inline-block px-1", MARK_CLASS[l.kind])}>Aa</span>
                          <span className="text-muted-foreground">{l.label}</span>
                        </span>
                      ))}
                    </div>
                    <div className="bg-muted/40 max-h-[28rem] overflow-auto rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">
                      <Segments segments={segments} />
                    </div>
                  </Section>

                  {summary && summary.citations.length > 0 && (
                    <Section title="Citations">
                      <ul className="flex flex-col gap-1 text-sm">
                        {summary.citations.map((c) => (
                          <li key={c.id} className="flex items-center gap-1.5">
                            {c.url ? (
                              <a href={c.url} target="_blank" rel="noreferrer" className="text-primary inline-flex items-center gap-1 break-all underline-offset-4 hover:underline">
                                {c.url}
                                <ExternalLinkIcon className="size-3 shrink-0" aria-hidden="true" />
                              </a>
                            ) : (
                              <span>{c.anchor_text ?? c.domain ?? "Unresolved citation"}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </Section>
                  )}

                  {summary && summary.claims.length > 0 && (
                    <Section title="Claims">
                      <ul className="flex flex-col gap-1 text-sm">
                        {summary.claims.map((c) => (
                          <li key={c.id}>
                            <span className="font-medium">{c.subject}</span> {c.predicate} {c.object}
                            <span className="text-muted-foreground ml-1 text-xs">({Math.round(c.confidence * 100)}% confidence)</span>
                          </li>
                        ))}
                      </ul>
                    </Section>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
