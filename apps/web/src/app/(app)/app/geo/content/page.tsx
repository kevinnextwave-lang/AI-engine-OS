"use client";

import { AiInsightCard } from "@/components/ai-insight-card";
import { MockNotice } from "@/components/geo/data-source-badge";
import { contentInsight } from "@/lib/ai-insights";
import { IssueExplorer } from "@/components/geo/issue-explorer";
import { GeoPageTools } from "@/components/geo/page-tools";
import { ScoreRing } from "@/components/geo/score-ring";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { Card, CardContent, Progress } from "@ai-search-growth-os/ui";

const CONTENT_SEO = new Set(["metadata", "headings"]);
const CONTENT_READINESS = new Set(["content_structure", "evidence", "faq", "comparison", "authority"]);

export default function ContentPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const issues = geo.issues.filter(
    (i) =>
      (i.origin === "technical_seo" && CONTENT_SEO.has(i.categoryKey)) ||
      (i.origin === "ai_readiness" && CONTENT_READINESS.has(i.categoryKey)),
  );
  const content = geo.readiness.categories.find((c) => c.key === "content_structure");
  const cards = geo.readiness.categories.filter((c) => ["content_structure", "evidence", "authority", "faq"].includes(c.key));

  return (
    <>
      <PageHeader title="Content" description="Titles, headings, specificity, evidence, authorship and FAQ coverage — the content-side signals from both audits.">
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />
      {(geo.error ?? geo.actionError) && (
        <p className="text-destructive mb-4 text-sm">{geo.error ?? geo.actionError}</p>
      )}

      <div className="mb-4 grid gap-4 lg:grid-cols-[auto_1fr]">
        <Card className="py-4">
          <CardContent className="flex items-center gap-5 px-5">
            <ScoreRing value={content?.applicable ? content.value : null} label="Content Quality" />
            <div className="text-sm">
              <p className="font-medium">Content Quality</p>
              <p className="text-muted-foreground mt-0.5 max-w-xs">{content?.explanation}</p>
              {content?.how && <p className="text-muted-foreground mt-1 font-mono text-xs">{content.how}</p>}
            </div>
          </CardContent>
        </Card>
        <Card className="py-4">
          <CardContent className="grid gap-4 px-5 sm:grid-cols-2">
            {cards.map((c) => {
              const measured = c.applicable && c.value != null;
              return (
                <div key={c.key} className="flex flex-col gap-1.5">
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium">{c.label}</span>
                    <span className="text-muted-foreground tabular-nums">{measured ? `${c.value}/100` : "–"}</span>
                  </div>
                  {/* No bar when unmeasured — an empty bar would read as a real 0. */}
                  {measured && <Progress value={c.value ?? 0} aria-label={c.label} />}
                  <p className="text-muted-foreground text-xs">{c.explanation}</p>
                </div>
              );
            })}
            {cards.some((c) => !(c.applicable && c.value != null)) && (
              <p className="text-muted-foreground text-xs sm:col-span-2">
                – means this audit didn&apos;t measure the signal; a 0 would be a real measured score.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {!loading && (
        <div className="mb-4">
          <AiInsightCard
            insight={contentInsight({
              issues,
              contentScore: content?.applicable ? content.value : null,
              auditTimestamp: geo.crawl.auditTimestamp,
            })}
            href="/app/agents/briefs"
          />
        </div>
      )}

      <IssueExplorer
        issues={issues}
        loading={loading}
        busy={geo.busy === "status"}
        onUpdateStatus={geo.actions.updateIssueStatus}
        emptyTitle="No content observations"
        emptyDescription="Run a GEO audit to analyze titles, headings, specificity, evidence and FAQ coverage."
      />
    </>
  );
}
