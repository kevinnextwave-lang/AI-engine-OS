"use client";

import { GlobeIcon, PlayIcon, RefreshCwIcon } from "lucide-react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { EmptyState } from "@/components/geo/empty-state";
import { GeoPageTools } from "@/components/geo/page-tools";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { formatDateTime, formatDuration, relativeTime } from "@/lib/geo/mappers";
import type { CrawlStatus } from "@ai-search-growth-os/types";
import { Badge, Button, Card, CardContent, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

const STATUS_VARIANT: Record<CrawlStatus | "never", "success" | "medium" | "high" | "muted" | "outline" | "low"> = {
  completed: "success",
  partially_completed: "medium",
  failed: "high",
  cancelled: "muted",
  queued: "low",
  running: "low",
  never: "outline",
};

function Stat({ label, value, loading }: { label: string; value: React.ReactNode; loading: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-muted-foreground text-xs font-medium">{label}</p>
      {loading ? <Skeleton className="h-7 w-24" /> : <p className="text-xl font-semibold tabular-nums">{value}</p>}
    </div>
  );
}

export default function WebsiteAuditPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const crawl = geo.crawl;
  const canAct = geo.source === "api" && geo.busy === null;
  const crawlActive = crawl.status === "queued" || crawl.status === "running";

  return (
    <>
      <PageHeader title="Website Audit" description="Crawl the site, then run the GEO audit over the collected pages.">
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />

      <Card className="mb-4 py-5">
        <CardContent className="px-5">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <p className="font-medium">Crawl status</p>
              {loading ? <Skeleton className="h-5 w-20" /> : <Badge variant={STATUS_VARIANT[crawl.status]}>{crawl.status.replace("_", " ")}</Badge>}
              {crawlActive && <RefreshCwIcon className="text-muted-foreground size-4 animate-spin" aria-label="Crawl in progress" />}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" disabled={!canAct || crawlActive} onClick={() => void geo.actions.runCrawl()}>
                <PlayIcon aria-hidden="true" />
                {geo.busy === "crawl" ? "Starting…" : "Run new crawl"}
              </Button>
              <Button
                disabled={!canAct || crawlActive || crawl.pagesCrawled === 0 || crawl.auditRunning}
                onClick={() => void geo.actions.runGeoAudit()}
                title={crawl.pagesCrawled === 0 ? "Run a crawl first" : undefined}
              >
                {geo.busy === "audit" ? "Starting…" : crawl.auditRunning ? "Audit running…" : "Run GEO audit"}
              </Button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-5 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Last crawl" value={crawl.lastCrawlAt ? relativeTime(crawl.lastCrawlAt) : "Never"} loading={loading} />
            <Stat label="Pages crawled" value={crawl.pagesCrawled} loading={loading} />
            <Stat label="Pages failed" value={crawl.pagesFailed} loading={loading} />
            <Stat label="Crawl duration" value={formatDuration(crawl.durationSeconds)} loading={loading} />
            <Stat label="Audit timestamp" value={crawl.auditTimestamp ? relativeTime(crawl.auditTimestamp) : "–"} loading={loading} />
            <Stat label="Root URL" value={<span className="truncate font-mono text-sm" title={crawl.job?.root_url}>{crawl.job?.root_url ?? "–"}</span>} loading={loading} />
          </div>
          {crawl.job?.error_message && <p className="text-destructive mt-4 text-sm">{crawl.job.error_message}</p>}
        </CardContent>
      </Card>

      {!loading && geo.raw.crawlJobs.length === 0 ? (
        <EmptyState icon={GlobeIcon} title="No crawls yet" description="Start a crawl to collect pages. The GEO audit, structured data and AI readiness views are built from what the crawl finds.">
          <Button disabled={!canAct} onClick={() => void geo.actions.runCrawl()}>Run new crawl</Button>
        </EmptyState>
      ) : (
        <div className="rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Started</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Discovered</TableHead>
                <TableHead className="text-right">Crawled</TableHead>
                <TableHead className="text-right">Failed</TableHead>
                <TableHead className="text-right">Skipped</TableHead>
                <TableHead className="text-right">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading
                ? Array.from({ length: 3 }, (_, i) => (
                    <TableRow key={i}>{Array.from({ length: 8 }, (_, j) => <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>)}</TableRow>
                  ))
                : geo.raw.crawlJobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell>{formatDateTime(job.started_at ?? job.created_at)}</TableCell>
                      <TableCell><Badge variant={STATUS_VARIANT[job.status]}>{job.status.replace("_", " ")}</Badge></TableCell>
                      <TableCell className="capitalize">{job.crawl_type.replace("_", " ")}</TableCell>
                      <TableCell className="text-right tabular-nums">{job.pages_discovered}</TableCell>
                      <TableCell className="text-right tabular-nums">{job.pages_crawled}</TableCell>
                      <TableCell className="text-right tabular-nums">{job.pages_failed}</TableCell>
                      <TableCell className="text-right tabular-nums">{job.pages_skipped}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatDuration(job.duration_seconds)}</TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
