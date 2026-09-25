"use client";

import Link from "next/link";
import * as React from "react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { IssueDrawer } from "@/components/geo/issue-drawer";
import { IssueExplorer } from "@/components/geo/issue-explorer";
import {
  GeoHero,
  GeoTrendChart,
  PriorityOpportunities,
  ScoreTile,
  ScoreTileSkeleton,
} from "@/components/geo/overview-sections";
import { AiInsightCard } from "@/components/ai-insight-card";
import { GeoPageTools } from "@/components/geo/page-tools";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { geoActionPlanInsight } from "@/lib/ai-insights";
import { aiRecommendations, geoTrends, metricChanges, overallScore, priorityOpportunities } from "@/lib/geo/overview";
import { Button } from "@ai-search-growth-os/ui";

/**
 * The GEO Overview dashboard, ordered by the product flow:
 * MEASURE (hero + scores) → UNDERSTAND (what each score means) →
 * PRIORITIZE (priority opportunities) → FIX (AI recommendations, issue triage)
 * → MEASURE AGAIN (score history when real audit history exists).
 *
 * Everything shown is derived from stored crawl/audit data; sections whose
 * data does not exist (e.g. trends before a second audit) render nothing.
 */
export default function GeoOverviewPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const [openIssueId, setOpenIssueId] = React.useState<string | null>(null);
  const openIssue = geo.issues.find((i) => i.id === openIssueId) ?? null;

  const overall = React.useMemo(() => overallScore(geo.metrics), [geo.metrics]);
  const changes = React.useMemo(
    () => metricChanges(geo.raw.seoAudits, geo.raw.readinessAudits),
    [geo.raw.seoAudits, geo.raw.readinessAudits],
  );
  const opportunities = React.useMemo(() => priorityOpportunities(geo.issues), [geo.issues]);
  const recommendations = React.useMemo(() => aiRecommendations(geo.issues), [geo.issues]);
  const pagesAnalyzedForPlan =
    geo.latestSeoAudit?.pages_analyzed ?? geo.raw.readiness?.pages_analyzed ?? geo.crawl.pagesCrawled;
  const actionPlan = React.useMemo(
    () =>
      geoActionPlanInsight({
        summary: geo.summary,
        opportunities,
        recommendations,
        pagesAnalyzed: pagesAnalyzedForPlan,
        auditTimestamp: geo.crawl.auditTimestamp,
      }),
    [geo.summary, opportunities, recommendations, pagesAnalyzedForPlan, geo.crawl.auditTimestamp],
  );
  const trends = React.useMemo(
    () => geoTrends(geo.raw.seoAudits, geo.raw.readinessAudits),
    [geo.raw.seoAudits, geo.raw.readinessAudits],
  );
  const pagesAnalyzed =
    geo.latestSeoAudit?.pages_analyzed ?? geo.raw.readiness?.pages_analyzed ?? geo.crawl.pagesCrawled;

  return (
    <>
      <PageHeader
        title="GEO Overview"
        description="How healthy the website is for AI search — measured from real crawl and audit data."
      >
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />
      {(geo.error ?? geo.actionError) && (
        <p className="text-destructive mb-4 text-sm">{geo.error ?? geo.actionError}</p>
      )}

      {/* MEASURE */}
      <GeoHero
        overall={overall}
        summary={geo.summary}
        auditTimestamp={geo.crawl.auditTimestamp}
        auditRunning={geo.crawl.auditRunning}
        pagesAnalyzed={pagesAnalyzed}
        loading={loading}
        actions={
          <>
            <Button
              size="sm"
              disabled={geo.source !== "api" || geo.busy !== null || geo.crawl.pagesCrawled === 0}
              onClick={() => void geo.actions.runGeoAudit()}
              title={geo.source !== "api" ? "Select a project to run audits" : undefined}
            >
              {geo.busy === "audit" ? "Starting…" : "Run GEO audit"}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/app/geo/website-audit">Website audit</Link>
            </Button>
          </>
        }
      />

      {/* UNDERSTAND */}
      <section aria-label="Supporting scores" className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        {loading
          ? Array.from({ length: 5 }, (_, i) => <ScoreTileSkeleton key={i} />)
          : geo.metrics.map((m) => <ScoreTile key={m.key} metric={m} change={changes[m.key]} />)}
      </section>

      {/* PRIORITIZE */}
      <section aria-label="Priority opportunities" className="mb-6">
        <div className="mb-3">
          <h2 className="text-lg font-semibold">Priority opportunities</h2>
          <p className="text-muted-foreground text-sm">
            The open findings with the biggest reach, ranked by severity. Fix these first.
          </p>
        </div>
        <PriorityOpportunities
          opportunities={opportunities}
          loading={loading}
          onReview={(o) => setOpenIssueId(o.issues[0]?.id ?? null)}
        />
      </section>

      {/* FIX — the shared AI Recommendation pattern, built from audit data */}
      {!loading && (
        <section aria-label="AI recommendation" className="mb-6">
          <AiInsightCard
            insight={actionPlan}
            onCta={() => setOpenIssueId(opportunities[0]?.issues[0]?.id ?? null)}
          />
        </section>
      )}

      {/* MEASURE AGAIN — only with real audit history */}
      {!loading && trends && (
        <section aria-label="Score history" className="mb-6">
          <GeoTrendChart series={trends} />
        </section>
      )}

      {/* Recent issues */}
      <section aria-label="Recent issues">
        <div className="mb-3 flex items-baseline justify-between">
          <div>
            <h2 className="text-lg font-semibold">Recent issues</h2>
            <p className="text-muted-foreground text-sm">Most severe first. Open a row for evidence and triage.</p>
          </div>
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
          limit={8}
        />
      </section>

      {/* Drawer for opportunities / recommendations (the issue table has its own) */}
      <IssueDrawer
        issue={openIssue}
        onClose={() => setOpenIssueId(null)}
        onUpdateStatus={geo.actions.updateIssueStatus}
        busy={geo.busy === "status"}
      />
    </>
  );
}
