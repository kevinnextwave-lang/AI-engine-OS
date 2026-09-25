"use client";

/**
 * One citation, explained as a chain rather than a table row:
 * when and which engine → the prompt asked → the answer it appeared in →
 * who it relates to → the source it points at. Raw identifiers live behind
 * a collapsed technical-details section (progressive disclosure).
 */

import { ChevronRightIcon, ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { fmtDateTime } from "@/components/visibility/format";
import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { CitationRow } from "@/lib/intelligence/types";
import {
  Badge,
  Button,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@ai-search-growth-os/ui";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** Hostname of the project site, for the "your website" flag. */
function siteHost(websiteUrl: string | null): string | null {
  if (!websiteUrl) return null;
  try {
    return new URL(websiteUrl).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export function CitationDrawer({
  citation,
  projectWebsiteUrl,
  onClose,
  onOpenSource,
}: {
  citation: CitationRow | null;
  projectWebsiteUrl: string | null;
  onClose: () => void;
  /** Opens the source profile drawer for this citation's domain. */
  onOpenSource?: (sourceDomainId: string) => void;
}) {
  const host = siteHost(projectWebsiteUrl);
  const c = citation;
  const isOwnSite =
    c?.domain != null && host != null && c.domain.replace(/^www\./, "") === host;
  const competitorRels = c?.relationships.filter((r) => r.relationship === "competitor") ?? [];
  const brandRels = c?.relationships.filter((r) => r.relationship === "brand") ?? [];

  return (
    <Sheet open={c !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        {c && (
          <>
            <SheetHeader className="pr-10">
              <div className="flex flex-wrap items-center gap-2">
                {isOwnSite && <Badge variant="success">Your website</Badge>}
                {competitorRels.length > 0 && <Badge variant="medium">Competitor cited</Badge>}
                {c.sourceType && <Badge variant="secondary">{SOURCE_TYPE_LABEL[c.sourceType]}</Badge>}
              </div>
              <SheetTitle className="text-lg leading-snug break-all">{c.domain ?? c.url ?? "Citation"}</SheetTitle>
              <SheetDescription>
                Observed {fmtDateTime(c.citedAt)} · {c.providerLabel}
                {c.model && <span className="ml-1 font-mono text-xs">{c.model}</span>}
              </SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-5 px-4 pb-6">
              <Section title="The prompt asked">
                <p className="text-sm leading-relaxed">“{c.prompt}”</p>
                <Link
                  href={`/app/ai-visibility/prompts?prompt=${c.promptId}`}
                  className="text-primary text-xs font-medium underline-offset-4 hover:underline"
                >
                  Read the full AI answer with highlights →
                </Link>
              </Section>

              <Section title="Relates to">
                {c.relationships.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    Not linked to your brand or a configured competitor — background material the engine drew on.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {brandRels.map((r) => (
                      <Badge key={r.name} variant="default" title={`confidence ${r.confidence}`}>
                        {r.name}
                      </Badge>
                    ))}
                    {competitorRels.map((r) => (
                      <Badge key={r.name} variant="medium" title={`confidence ${r.confidence}`}>
                        {r.name}
                      </Badge>
                    ))}
                  </div>
                )}
              </Section>

              <Section title="The source it points at">
                <div className="flex flex-col gap-1 text-sm">
                  <p>
                    <span className="font-medium">{c.domain ?? "Unknown domain"}</span>
                    {isOwnSite ? (
                      <span className="text-success ml-2 text-xs font-medium">This is your website</span>
                    ) : (
                      c.sourceType && <span className="text-muted-foreground ml-2 text-xs">{SOURCE_TYPE_LABEL[c.sourceType]}</span>
                    )}
                  </p>
                  {c.url && (
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary inline-flex items-center gap-1 text-xs break-all underline-offset-4 hover:underline"
                    >
                      {c.url}
                      <ExternalLinkIcon className="size-3 shrink-0" aria-hidden="true" />
                    </a>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {c.sourceDomainId && onOpenSource && (
                    <Button size="sm" variant="outline" onClick={() => onOpenSource(c.sourceDomainId!)}>
                      Open source profile
                    </Button>
                  )}
                  <Button asChild size="sm" variant="ghost">
                    <Link href="/app/ai-intelligence/claims">Claims these answers repeat</Link>
                  </Button>
                </div>
              </Section>

              {/* Progressive disclosure: identifiers and parser fields. */}
              <details className="group rounded-lg border">
                <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1.5 px-3 py-2 text-xs font-semibold tracking-wide uppercase select-none">
                  <ChevronRightIcon className="size-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
                  Technical details
                </summary>
                <div className="grid grid-cols-[8rem_1fr] gap-2 border-t px-3 py-3 text-xs">
                  <span className="text-muted-foreground font-mono">citation id</span>
                  <span className="font-mono break-all">{c.id}</span>
                  <span className="text-muted-foreground font-mono">prompt id</span>
                  <span className="font-mono break-all">{c.promptId}</span>
                  <span className="text-muted-foreground font-mono">run id</span>
                  <span className="font-mono break-all">{c.runId}</span>
                  {c.provider && (
                    <>
                      <span className="text-muted-foreground font-mono">provider</span>
                      <span className="font-mono">{c.provider}</span>
                    </>
                  )}
                </div>
              </details>
              <Separator />
              <p className="text-muted-foreground text-xs">
                A citation is one link an AI answer pointed at. Its source profile aggregates every answer citing the
                same domain; claims track the statements those answers repeat.
              </p>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
