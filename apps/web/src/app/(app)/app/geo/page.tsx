"use client";

import Link from "next/link";

import { MockNotice } from "@/components/geo/data-source-badge";
import { IssueExplorer } from "@/components/geo/issue-explorer";
import { MetricCard, MetricCardSkeleton } from "@/components/geo/metric-card";
import { GeoPageTools } from "@/components/geo/page-tools";
import { SeveritySummary } from "@/components/geo/severity-summary";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@ai-search-growth-os/ui";

export default function GeoOverviewPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;

  return (
    <>
      <PageHeader
        title="GEO Overview"
        description="How clearly the website can be crawled, understood and cited. Scores are internal metrics derived from audit observations."
      >
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />
      {geo.error && <p className="text-destructive mb-4 text-sm">{geo.error}</p>}

      <section aria-label="Primary metrics" className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        {loading
          ? Array.from({ length: 5 }, (_, i) => <MetricCardSkeleton key={i} />)
          : geo.metrics.map((m) => <MetricCard key={m.key} metric={m} />)}
      </section>

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SeveritySummary summary={geo.summary} loading={loading} />
        </div>
        <div className="bg-card flex flex-col justify-between gap-3 rounded-xl border p-5 text-sm shadow-sm">
          <div>
            <p className="font-medium">Audits</p>
            <p className="text-muted-foreground mt-1">
              {geo.crawl.auditRunning
                ? "An audit is running — results refresh automatically."
                : geo.crawl.auditTimestamp
                  ? `Last audit ${new Date(geo.crawl.auditTimestamp).toLocaleString()}`
                  : "No audit has been run for this project yet."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/app/geo/website-audit">Website audit</Link>
            </Button>
            <Button
              size="sm"
              disabled={geo.source !== "api" || geo.busy !== null || geo.crawl.pagesCrawled === 0}
              onClick={() => void geo.actions.runGeoAudit()}
              title={geo.source !== "api" ? "Select a project to run audits" : undefined}
            >
              {geo.busy === "audit" ? "Starting…" : "Run GEO audit"}
            </Button>
          </div>
        </div>
      </div>

      <section aria-label="Issues">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Issues</h2>
          <Link href="/app/geo/technical-seo" className="text-primary text-sm underline-offset-4 hover:underline">
            Open full table
          </Link>
        </div>
        <IssueExplorer
          issues={geo.issues}
          loading={loading}
          busy={geo.busy === "status"}
          onUpdateStatus={geo.actions.updateIssueStatus}
          showFilters={false}
          limit={12}
        />
      </section>
    </>
  );
}
