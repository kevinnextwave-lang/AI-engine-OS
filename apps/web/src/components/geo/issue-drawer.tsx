"use client";

import { BotIcon, ExternalLinkIcon } from "lucide-react";
import * as React from "react";

import { SeverityBadge, StatusBadge } from "@/components/geo/severity-badge";
import { STATUS_LABEL } from "@/lib/geo/labels";
import type { GeoIssue } from "@/lib/geo/types";
import type { ObservationStatus } from "@ai-search-growth-os/types";
import {
  Badge,
  Button,
  Input,
  NativeSelect,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@ai-search-growth-os/ui";

const WHY_IT_MATTERS: Record<string, string> = {
  technical_seo:
    "Technical issues change how reliably crawlers can fetch, index and interpret a page. Fixing them removes ambiguity; it does not by itself guarantee a change in rankings or in how AI systems cite the site.",
  ai_readiness:
    "This is an AI readability signal: it affects how clearly a reader — human or machine — can identify what the page or company is about. Signals like this are not claims about AI ranking; they make the site's facts easier to find, attribute and cite.",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** Evidence keys already shown as "Affected pages" are omitted here. */
function EvidenceList({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence).filter(([k]) => k !== "urls" && k !== "count");
  if (entries.length === 0) return <p className="text-muted-foreground text-sm">No additional evidence recorded.</p>;
  return (
    <dl className="grid gap-1.5 text-sm">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[8rem_1fr] gap-2">
          <dt className="text-muted-foreground truncate font-mono text-xs leading-5" title={key}>
            {key}
          </dt>
          <dd className="min-w-0">
            {typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? (
              <span className="break-words">{String(value)}</span>
            ) : (
              <pre className="bg-muted max-h-48 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(value, null, 2)}
              </pre>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function StatusForm({
  issue,
  onUpdateStatus,
  busy,
}: {
  issue: GeoIssue;
  onUpdateStatus: (issue: GeoIssue, status: ObservationStatus, note?: string) => Promise<void>;
  busy: boolean;
}) {
  const [status, setStatus] = React.useState<ObservationStatus>(issue.status);
  const [note, setNote] = React.useState(issue.statusNote ?? "");
  const unchanged = status === issue.status && (note.trim() || null) === issue.statusNote;
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void onUpdateStatus(issue, status, note.trim() || undefined);
      }}
    >
      <div className="grid grid-cols-[10rem_1fr] gap-2">
        <NativeSelect value={status} onChange={(e) => setStatus(e.target.value as ObservationStatus)} aria-label="Status">
          {(Object.keys(STATUS_LABEL) as ObservationStatus[]).map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" maxLength={1000} />
      </div>
      <div>
        <Button type="submit" size="sm" disabled={busy || unchanged}>
          {busy ? "Saving…" : "Update status"}
        </Button>
      </div>
    </form>
  );
}

export function IssueDrawer({
  issue,
  onClose,
  onUpdateStatus,
  busy,
}: {
  issue: GeoIssue | null;
  onClose: () => void;
  onUpdateStatus: (issue: GeoIssue, status: ObservationStatus, note?: string) => Promise<void>;
  busy: boolean;
}) {
  return (
    <Sheet open={issue !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        {issue && (
          <>
            <SheetHeader className="pr-10">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={issue.severity} />
                <Badge variant="secondary">{issue.category}</Badge>
                <StatusBadge status={issue.status} />
              </div>
              <SheetTitle className="text-lg leading-snug">{issue.title}</SheetTitle>
              <SheetDescription className="font-mono text-xs">{issue.code}</SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-5 px-4 pb-6">
              <Section title="Problem">
                <p className="text-sm leading-relaxed">{issue.description}</p>
              </Section>
              <Section title="Evidence">
                {issue.url && (
                  <a
                    href={issue.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary inline-flex items-center gap-1 font-mono text-xs break-all underline-offset-4 hover:underline"
                  >
                    {issue.url}
                    <ExternalLinkIcon className="size-3 shrink-0" aria-hidden="true" />
                  </a>
                )}
                <EvidenceList evidence={issue.evidence} />
              </Section>
              <Section title="Why it matters">
                <p className="text-muted-foreground text-sm leading-relaxed">{WHY_IT_MATTERS[issue.origin]}</p>
              </Section>
              <Section title="Recommendation">
                <p className="text-sm leading-relaxed">{issue.recommendation}</p>
              </Section>
              <Section title={`Affected pages (${issue.affectedCount})`}>
                {issue.affectedPages.length === 0 ? (
                  <p className="text-muted-foreground text-sm">Site-wide; no individual pages listed.</p>
                ) : (
                  <ul className="flex max-h-56 flex-col gap-1 overflow-auto text-xs">
                    {issue.affectedPages.map((url) => (
                      <li key={url}>
                        <a href={url} target="_blank" rel="noreferrer" className="font-mono break-all underline-offset-4 hover:underline">
                          {url}
                        </a>
                      </li>
                    ))}
                    {issue.affectedCount > issue.affectedPages.length && (
                      <li className="text-muted-foreground">
                        …and {issue.affectedCount - issue.affectedPages.length} more
                      </li>
                    )}
                  </ul>
                )}
              </Section>
              <Separator />
              <Section title="Status">
                {issue.canUpdateStatus ? (
                  <StatusForm key={`${issue.id}:${issue.status}:${issue.statusNote ?? ""}`} issue={issue} onUpdateStatus={onUpdateStatus} busy={busy} />
                ) : (
                  <p className="text-muted-foreground text-sm">
                    AI readiness observations are regenerated on every audit and cannot be triaged yet.
                  </p>
                )}
              </Section>
              <Separator />
              <Section title="Future">
                <Button variant="outline" disabled title="Connected in a future milestone" className="w-fit">
                  <BotIcon aria-hidden="true" />
                  Fix with AI Agent
                </Button>
                <p className="text-muted-foreground text-xs">Automated fixes will be connected in a future milestone.</p>
              </Section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
