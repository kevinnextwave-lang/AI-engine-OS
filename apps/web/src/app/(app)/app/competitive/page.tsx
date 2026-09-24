"use client";

import * as React from "react";

import { DrawerSection, EvidenceList } from "@/components/section/evidence";
import { DataTable, StatusBadge } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { CompetitiveAdvantage, CompetitiveOverview, VisibilityWindow } from "@ai-search-growth-os/types";
import { Badge, Card, CardContent, CardHeader, CardTitle, NativeSelect, TableCell, TableRow } from "@ai-search-growth-os/ui";
import { MinusIcon, TrendingDownIcon, TrendingUpIcon } from "lucide-react";

const WINDOWS: VisibilityWindow[] = ["7d", "30d", "90d"];

function fmtShare(v: number | null): string {
  return v == null ? "—" : `${v}%`;
}

function Trend({ trend, change }: { trend: string; change: number | null }) {
  const Icon = trend === "up" ? TrendingUpIcon : trend === "down" ? TrendingDownIcon : MinusIcon;
  const color = trend === "up" ? "text-emerald-600" : trend === "down" ? "text-red-600" : "text-muted-foreground";
  return (
    <span className={`inline-flex items-center gap-1 tabular-nums ${color}`}>
      <Icon className="size-3.5" aria-hidden="true" />
      {change == null ? "" : change > 0 ? `+${change}` : change}
    </span>
  );
}

function AdvantageCard({ adv }: { adv: CompetitiveAdvantage }) {
  // `advantage` is competitor_score − brand_score: positive means the
  // competitor leads, negative means your brand leads.
  const gap = adv.advantage;
  const ahead = gap != null && gap > 0;
  const label =
    gap == null
      ? "not enough data"
      : ahead
        ? `+${gap} pts ahead of you`
        : gap < 0
          ? `${Math.abs(gap)} pts behind you`
          : "level with you";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span>{adv.competitor}</span>
          <span className="flex items-center gap-2">
            {adv.material && ahead && <Badge variant="high">material</Badge>}
            <span
              className={`text-sm font-normal tabular-nums ${ahead ? "text-red-600" : "text-muted-foreground"}`}
            >
              {label}
            </span>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {adv.reason && <p className="text-muted-foreground">{adv.reason}</p>}
        {ahead && adv.where_they_win.length > 0 && (
          <p>
            <span className="text-muted-foreground">Where they lead: </span>
            {adv.where_they_win.join(", ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function CompetitiveOverviewPage() {
  const [window, setWindow] = React.useState<VisibilityWindow>("30d");
  const res = useProjectResource<CompetitiveOverview>(
    React.useCallback((pid) => api.competitiveVisibility.overview(pid, window), [window]),
  );
  const d = res.data;
  const insufficient = d != null && d.data_quality.sample_size < d.data_quality.minimum_sample;

  return (
    <SectionFrame
      title="Competitive Visibility"
      description="How often AI answers mention, recommend and cite your brand versus each configured competitor. The score is this product's own composite of measured shares — not an industry-standard metric."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <NativeSelect aria-label="Window" value={window} onChange={(e) => setWindow(e.target.value as VisibilityWindow)} className="w-28">
          {WINDOWS.map((w) => (
            <option key={w} value={w}>
              Last {w.replace("d", " days")}
            </option>
          ))}
        </NativeSelect>
      }
    >
      {d && (
        <Toolbar>
          <span className="text-muted-foreground text-xs">
            {d.data_quality.sample_size} responses · {d.data_quality.prompt_count} prompts ·{" "}
            {d.data_quality.provider_count} engines · confidence{" "}
            <StatusBadge value={d.data_quality.confidence} className="align-middle" /> · generated{" "}
            {fmtDateTime(d.generated_at)}
          </span>
        </Toolbar>
      )}
      {insufficient && d && (
        <p className="border-muted bg-muted/30 text-muted-foreground mb-4 rounded-lg border p-3 text-sm">
          Only {d.data_quality.sample_size} responses in this window (minimum {d.data_quality.minimum_sample} for scores). Run more prompts or widen the window.
        </p>
      )}
      <DataTable
        head={["Entity", "Score", "Change", "Mentions", "Recommended", "Avg. position", "Citations", "Sentiment", "Prompt coverage"]}
        loading={res.loading}
        empty={d && d.entities.length === 0 ? "No competitors configured yet — add them in project settings or review discovery candidates." : null}
      >
        {(d?.entities ?? []).map((e) => (
          <TableRow key={e.name} className={e.is_brand ? "bg-primary/5 font-medium" : undefined}>
            <TableCell>
              {e.is_brand ? "Your brand" : e.name}
              {e.sufficiency === "insufficient" && (
                <Badge variant="muted" className="ml-2">low data</Badge>
              )}
            </TableCell>
            <TableCell className="tabular-nums">{e.score ?? "—"}</TableCell>
            <TableCell>
              <Trend trend={e.trend} change={e.change} />
            </TableCell>
            <TableCell className="tabular-nums">{fmtShare(e.mention_share)}</TableCell>
            <TableCell className="tabular-nums">{fmtShare(e.recommendation_share)}</TableCell>
            <TableCell className="tabular-nums">{e.average_position ?? "—"}</TableCell>
            <TableCell className="tabular-nums">{fmtShare(e.citation_share)}</TableCell>
            <TableCell className="tabular-nums">{e.sentiment_score ?? "—"}</TableCell>
            <TableCell className="tabular-nums">{e.prompt_coverage}</TableCell>
          </TableRow>
        ))}
      </DataTable>
      {d && d.ranking.available && d.ranking.brand_rank != null && (
        <p className="mt-4 text-sm">
          Ranking: <strong>#{d.ranking.brand_rank}</strong> of {d.ranking.order.length} ({d.ranking.order.join(" › ")})
        </p>
      )}
      {d && !d.ranking.available && d.ranking.reason && (
        <p className="text-muted-foreground mt-4 text-sm">Ranking unavailable — {d.ranking.reason}</p>
      )}
      {d && d.advantages.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-1 text-lg font-semibold">Competitive gap by competitor</h2>
          {!d.advantages.some((a) => a.advantage != null && a.advantage > 0) && (
            <p className="text-muted-foreground mb-3 text-sm">
              Your brand currently leads every configured competitor in this window.
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            {d.advantages.map((a) => (
              <AdvantageCard key={a.competitor} adv={a} />
            ))}
          </div>
        </div>
      )}
      {d && (
        <div className="mt-6">
          <DrawerSection title="Method">
            <p className="text-muted-foreground text-sm">{d.note}</p>
            <EvidenceList evidence={{ weights: d.weights, material_advantage_threshold: d.material_advantage_threshold }} />
          </DrawerSection>
        </div>
      )}
    </SectionFrame>
  );
}
