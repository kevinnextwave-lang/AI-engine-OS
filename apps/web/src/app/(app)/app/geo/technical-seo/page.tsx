"use client";

import { MockNotice } from "@/components/geo/data-source-badge";
import { IssueExplorer } from "@/components/geo/issue-explorer";
import { GeoPageTools } from "@/components/geo/page-tools";
import { ScoreRing } from "@/components/geo/score-ring";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { relativeTime } from "@/lib/geo/mappers";
import { Card, CardContent } from "@ai-search-growth-os/ui";

export default function TechnicalSeoPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const issues = geo.issues.filter((i) => i.origin === "technical_seo");
  const audit = geo.latestSeoAudit;

  return (
    <>
      <PageHeader title="Technical SEO" description="Crawlability, indexability, metadata, canonicals, links, HTTP and structured-data observations from the latest technical audit.">
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />

      <Card className="mb-4 py-4">
        <CardContent className="flex flex-wrap items-center gap-5 px-5">
          <ScoreRing value={audit?.health_score ?? null} label="Technical SEO Health" />
          <div className="text-sm">
            <p className="font-medium">Technical SEO Health</p>
            <p className="text-muted-foreground mt-0.5 max-w-xl">
              Internal 0–100 score: 100 minus capped, severity-weighted deductions per category, scaled by the share of pages affected. Not an industry benchmark.
            </p>
            <p className="text-muted-foreground mt-1 text-xs">
              {audit ? `${audit.pages_analyzed} pages analyzed · ${audit.observation_count} observations · ${relativeTime(audit.completed_at)}` : "No completed audit"}
            </p>
          </div>
        </CardContent>
      </Card>

      <IssueExplorer issues={issues} loading={loading} busy={geo.busy === "status"} onUpdateStatus={geo.actions.updateIssueStatus} showOrigin={false} />
    </>
  );
}
