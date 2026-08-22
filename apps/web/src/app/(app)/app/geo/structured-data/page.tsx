"use client";

import { BracesIcon, LinkIcon } from "lucide-react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { EmptyState } from "@/components/geo/empty-state";
import { GeoPageTools } from "@/components/geo/page-tools";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { relativeTime } from "@/lib/geo/mappers";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Progress, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

function Stat({ label, value, loading, hint }: { label: string; value: React.ReactNode; loading: boolean; hint?: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="px-5">
        <p className="text-muted-foreground text-xs font-medium">{label}</p>
        {loading ? <Skeleton className="mt-1 h-8 w-16" /> : <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>}
        {hint && <p className="text-muted-foreground mt-1 text-xs">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export default function StructuredDataPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const sd = geo.structured;
  const org = geo.raw.entities?.organization ?? null;
  const consistency = geo.raw.consistency;
  const coverage = sd.pagesCrawled ? Math.round((100 * sd.pagesWithSchema) / sd.pagesCrawled) : 0;
  const maxPages = Math.max(1, ...sd.schemaTypes.map((t) => t.pages));

  return (
    <>
      <PageHeader title="Structured Data" description="Schema.org markup found across crawled pages, its validity, and the entities and relationships it declares.">
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />

      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Pages with schema" value={`${sd.pagesWithSchema} / ${sd.pagesCrawled}`} hint={`${coverage}% coverage`} loading={loading} />
        <Stat label="Schema blocks" value={sd.blocksTotal} hint={Object.entries(sd.formats).map(([f, n]) => `${n} ${f.replace("_", "-")}`).join(" · ") || "–"} loading={loading} />
        <Stat label="Invalid blocks" value={sd.blocksInvalid} hint="Could not be parsed" loading={loading} />
        <Stat label="Last analysis" value={sd.analyzedAt ? relativeTime(sd.analyzedAt) : "–"} loading={loading} />
      </div>

      {!loading && sd.pagesCrawled === 0 ? (
        <EmptyState icon={BracesIcon} title="No structured data analysis yet" description="Run a crawl and a GEO audit. Structured data is extracted from every crawled page and analyzed afterwards." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Schema types</CardTitle>
              <CardDescription>Pages declaring each type. Tracked types are marked; absence is informational — not every site needs every type.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {loading
                ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)
                : sd.schemaTypes.map((t) => (
                    <div key={t.type} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3 text-sm">
                      <span className="flex items-center gap-1.5 truncate font-mono text-xs">
                        {t.type}
                        {t.known && <Badge variant="secondary" className="px-1 py-0 text-[10px]">tracked</Badge>}
                      </span>
                      <Progress value={(100 * t.pages) / maxPages} aria-label={`${t.type} on ${t.pages} pages`} />
                      <span className="text-right tabular-nums">{t.pages}</span>
                    </div>
                  ))}
              {!loading && sd.knownTypesAbsent.length > 0 && (
                <div className="mt-2 border-t pt-3">
                  <p className="text-muted-foreground mb-1.5 text-xs font-medium">Tracked types not found</p>
                  <div className="flex flex-wrap gap-1">
                    {sd.knownTypesAbsent.map((t) => <Badge key={t} variant="outline" className="font-mono text-[11px]">{t}</Badge>)}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Invalid schema</CardTitle>
              <CardDescription>{sd.note}</CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-24 w-full" />
              ) : sd.invalidIssues.length === 0 ? (
                <p className="text-muted-foreground text-sm">No structural issues detected.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent"><TableHead>Issue</TableHead><TableHead className="text-right">Blocks</TableHead></TableRow>
                  </TableHeader>
                  <TableBody>
                    {sd.invalidIssues.map((i) => (
                      <TableRow key={i.code}><TableCell className="font-mono text-xs">{i.code}</TableCell><TableCell className="text-right tabular-nums">{i.count}</TableCell></TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {!loading && (geo.raw.schema?.issues.length ?? 0) > 0 && (
                <ul className="mt-3 flex max-h-48 flex-col gap-1.5 overflow-auto border-t pt-3 text-xs">
                  {geo.raw.schema!.issues.slice(0, 25).map((i) => (
                    <li key={i.id} className="flex flex-col">
                      <span><Badge variant="outline" className="mr-1 font-mono text-[10px]">{i.code}</Badge>{i.message}</span>
                      <span className="text-muted-foreground truncate font-mono">{i.page_url}{i.json_path ? ` · ${i.json_path}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Entity relationships</CardTitle>
              <CardDescription>The consolidated organization entity, its external profiles (sameAs), and facts that differ between pages.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-6 md:grid-cols-2">
              {loading ? (
                <Skeleton className="h-32 w-full md:col-span-2" />
              ) : !org ? (
                <p className="text-muted-foreground text-sm md:col-span-2">No organization entity could be consolidated — add Organization schema to the homepage.</p>
              ) : (
                <>
                  <div className="text-sm">
                    <p className="text-lg font-semibold">{org.name}</p>
                    <p className="text-muted-foreground font-mono text-xs">{org.entity_type}{org.url ? ` · ${org.url}` : ""}</p>
                    {org.description && <p className="mt-2">{org.description}</p>}
                    <p className="text-muted-foreground mt-2 text-xs">
                      Confidence: <span className="font-medium">{String(org.properties._confidence ?? "unknown")}</span> · derived from page schema, About/Contact pages and visible contact details.
                    </p>
                    <div className="mt-3 flex flex-col gap-1">
                      {org.links.length === 0 && <p className="text-muted-foreground text-xs">No sameAs profiles declared.</p>}
                      {org.links.map((l) => (
                        <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-xs underline-offset-4 hover:underline">
                          <LinkIcon className="size-3 shrink-0" aria-hidden="true" />
                          <Badge variant={l.is_authoritative ? "success" : "secondary"} className="px-1 py-0 text-[10px]">{l.platform}</Badge>
                          <span className="truncate font-mono">{l.url}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                  <div className="text-sm">
                    <p className="font-medium">Cross-page consistency</p>
                    <p className="text-muted-foreground mt-0.5 text-xs">{consistency?.note}</p>
                    {(consistency?.items.length ?? 0) === 0 ? (
                      <p className="text-muted-foreground mt-3 text-sm">No conflicts among {consistency?.entities_compared ?? 0} compared entities.</p>
                    ) : (
                      <ul className="mt-3 flex flex-col gap-2">
                        {consistency!.items.map((o) => (
                          <li key={o.id} className="rounded-md border p-2.5">
                            <p className="font-medium">{o.title}</p>
                            <p className="text-muted-foreground mt-0.5 text-xs">{o.description}</p>
                            {Array.isArray(o.evidence.values) && (
                              <ul className="mt-1.5 flex flex-wrap gap-1">
                                {(o.evidence.values as Array<{ value: unknown; pages?: string[] }>).map((v, i) => (
                                  <li key={i}><Badge variant="outline" className="font-mono text-[11px]" title={(v.pages ?? []).join("\n")}>{String(v.value)}</Badge></li>
                                ))}
                              </ul>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
