"use client";

import { BrainCircuitIcon } from "lucide-react";
import * as React from "react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { EmptyState } from "@/components/geo/empty-state";
import { IssueDrawer } from "@/components/geo/issue-drawer";
import { GeoPageTools } from "@/components/geo/page-tools";
import { ScoreRing } from "@/components/geo/score-ring";
import { SeverityBadge } from "@/components/geo/severity-badge";
import { useProjectGeo } from "@/components/geo/use-project-geo";
import { PageHeader } from "@/components/shell/page-header";
import { readinessObservationToIssue, relativeTime } from "@/lib/geo/mappers";
import type { GeoIssue, ReadinessCategoryView } from "@/lib/geo/types";
import { Badge, Button, Card, CardContent, Progress, Skeleton } from "@ai-search-growth-os/ui";

const SHOWN: ReadinessCategoryView["key"][] = ["entity_clarity", "product_clarity", "evidence", "content_structure", "factual_consistency", "authority", "faq", "comparison"];

function CategoryCard({ category, onOpen }: { category: ReadinessCategoryView; onOpen: (issue: GeoIssue) => void }) {
  const actionable = category.observations.filter((o) => o.severity !== "info");
  return (
    <Card className="gap-3 py-5">
      <CardContent className="flex flex-col gap-3 px-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-medium">{category.label}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">Weight {category.weight}{!category.applicable && category.weight > 0 ? " · not applicable to this site" : category.weight === 0 ? " · informational" : ""}</p>
          </div>
          <span className="text-2xl font-semibold tabular-nums">{category.applicable && category.value != null ? category.value : <span className="text-muted-foreground text-base">n/a</span>}</span>
        </div>
        <Progress value={category.applicable ? (category.value ?? 0) : 0} aria-label={category.label} />
        <p className="text-muted-foreground text-sm leading-relaxed">{category.explanation}</p>
        {category.how && <p className="text-muted-foreground font-mono text-xs">{category.how}</p>}
        {category.observations.length > 0 && (
          <ul className="flex flex-col gap-1.5 border-t pt-3">
            {category.observations.map((o) => (
              <li key={o.id}>
                <button type="button" onClick={() => onOpen(readinessObservationToIssue(o))} className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm">
                  <SeverityBadge severity={o.severity} />
                  <span className="truncate">{o.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {category.observations.length === 0 && actionable.length === 0 && <p className="text-muted-foreground border-t pt-3 text-xs">No observations.</p>}
      </CardContent>
    </Card>
  );
}

export default function AiReadinessPage() {
  const geo = useProjectGeo();
  const loading = geo.loading || geo.projectLoading;
  const r = geo.readiness;
  const [open, setOpen] = React.useState<GeoIssue | null>(null);
  const hasAudit = geo.raw.readiness !== null;

  return (
    <>
      <PageHeader title="AI Readiness" description="Deterministic signals about how clearly the site communicates its entities, offerings, authorship and evidence. No AI system is queried.">
        <GeoPageTools source={geo.source} reason={geo.mockReason} />
      </PageHeader>
      <MockNotice source={geo.source} reason={geo.mockReason} />

      <Card className="mb-4 py-5">
        <CardContent className="flex flex-wrap items-center gap-6 px-5">
          {loading ? <Skeleton className="size-28 rounded-full" /> : <ScoreRing value={r.score} size={112} stroke={10} label="AI Readiness Score" />}
          <div className="max-w-2xl text-sm">
            <div className="flex items-center gap-2">
              <p className="text-lg font-semibold">AI Readiness Score</p>
              <Badge variant="outline">internal metric</Badge>
            </div>
            <p className="text-muted-foreground mt-1 leading-relaxed">{r.note}</p>
            <p className="text-muted-foreground mt-2 text-xs">
              Weighted coverage of the categories below; categories that do not apply to this site are excluded and their weight redistributed.
              {r.completedAt ? ` Last audit ${relativeTime(r.completedAt)}.` : ""}
            </p>
          </div>
        </CardContent>
      </Card>

      {!loading && !hasAudit ? (
        <EmptyState icon={BrainCircuitIcon} title="No AI readiness audit yet" description="Run a crawl, then a GEO audit. The readiness analysis uses crawled pages and the structured-data entity layer.">
          <Button disabled={geo.source !== "api" || geo.busy !== null || geo.crawl.pagesCrawled === 0} onClick={() => void geo.actions.runGeoAudit()}>Run GEO audit</Button>
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {loading
            ? Array.from({ length: 6 }, (_, i) => <Card key={i} className="py-5"><CardContent className="flex flex-col gap-3 px-5"><Skeleton className="h-5 w-32" /><Skeleton className="h-2 w-full" /><Skeleton className="h-12 w-full" /></CardContent></Card>)
            : SHOWN.map((key) => {
                const c = r.categories.find((x) => x.key === key);
                return c ? <CategoryCard key={key} category={c} onOpen={setOpen} /> : null;
              })}
        </div>
      )}
      <IssueDrawer issue={open} onClose={() => setOpen(null)} onUpdateStatus={geo.actions.updateIssueStatus} busy={false} />
    </>
  );
}
