"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { SourceDrawer } from "@/components/intelligence/source-drawer";
import { useProject } from "@/components/project-provider";
import { SectionHeader } from "@/components/shell/section-header";
import { CompetitorTable } from "@/components/visibility/competitor-table";
import { CitationOverlap, CompetitorPrompts } from "@/components/visibility/competitor-evidence";
import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { TrendChart } from "@/components/visibility/trend-chart";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import { citationRows } from "@/lib/intelligence/mappers";
import type { SourceRow } from "@/lib/intelligence/types";
import type { ChartMode } from "@/lib/visibility/types";
import { Badge, Button } from "@ai-search-growth-os/ui";

/**
 * The Competitors experience: who appears alongside you in AI answers, where
 * they are cited, which prompts surface them, and where to act. Comparison →
 * evidence → action, all from measured data:
 * - comparison + trends come from the visibility window's response shares
 * - citation/prompt evidence comes from observed citations (its own window,
 *   labeled) — selecting a competitor in the table narrows the evidence
 */
export default function CompetitorsPage() {
  const vis = useProjectVisibility();
  const intel = useProjectIntelligence();
  const { current } = useProject();
  const loading = vis.loading || vis.projectLoading;
  const intelLoading = intel.loading || intel.projectLoading;
  const [mode, setMode] = React.useState<ChartMode>("competitor");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [openSource, setOpenSource] = React.useState<SourceRow | null>(null);

  const competitive = vis.metrics.find((m) => m.key === "competitive_share") ?? null;
  const ahead = vis.competitorsAhead.length;
  const intelCitations = React.useMemo(() => citationRows(intel.raw?.citations ?? []), [intel.raw?.citations]);
  const intelWindowLabel = `last ${intel.window.replace("d", " days")}`;

  return (
    <VisibilityPageFrame
      vis={vis}
      title="Competitors"
      description="Who AI engines put alongside you: measured mention shares, the sources competitor answers cite, and the prompts where they appear. Only competitors you configure are compared."
    >
      {/* Overview facts — all measured. */}
      {!loading && vis.competitorsConfigured > 0 && (
        <p className="text-muted-foreground mb-4 text-sm">
          <strong className="text-foreground tabular-nums">{vis.competitorsConfigured}</strong> configured ·{" "}
          <strong className={ahead > 0 ? "text-warning tabular-nums" : "text-success tabular-nums"}>{ahead}</strong>{" "}
          mentioned more often than {vis.brandName} ·{" "}
          {competitive?.value != null ? (
            <>
              competitive share <strong className="text-foreground tabular-nums">{competitive.value}/100</strong>
              <span> (100 = you lead)</span>
            </>
          ) : (
            <span>{competitive?.unavailableReason ?? "share not measurable yet"}</span>
          )}
        </p>
      )}

      {/* 1. Comparison — click a competitor to focus the evidence below. */}
      <section aria-label="AI visibility comparison" className="mb-6">
        <SectionHeader
          title="AI visibility comparison"
          hint="Share of this window's answers naming each brand. Click a competitor to focus the evidence below."
        />
        <CompetitorTable
          rows={vis.competitors}
          loading={loading}
          detailed
          competitorsConfigured={vis.competitorsConfigured}
          selected={selected}
          onSelect={setSelected}
        />
      </section>

      {selected && (
        <div className="bg-sidebar-accent/40 mb-6 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
          <span>
            Showing evidence for <strong>{selected}</strong>
          </span>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected(null)}>
            <XIcon aria-hidden="true" />
            All competitors
          </Button>
        </div>
      )}

      {/* 2. Trends */}
      <section aria-label="Visibility trends" className="mb-6">
        <TrendChart series={vis.chart} mode={mode} onModeChange={setMode} loading={loading} modes={["overall", "competitor"]} />
      </section>

      {/* 3. Evidence: citations */}
      <section aria-label="Citation overlap" className="mb-6">
        <SectionHeader
          title="Where competitors are cited"
          hint={`Sources cited by competitor-related answers (${intelWindowLabel}); a 0 in “Your citations” marks visibility they have that you don't. Click a source for its profile.`}
        />
        <CitationOverlap sources={intel.sources} selectedCompetitor={selected} loading={intelLoading} onOpenSource={setOpenSource} />
      </section>

      {/* 4. Evidence: prompts */}
      <section aria-label="Prompt overlap" className="mb-6">
        <SectionHeader
          title="Prompts where competitors appear"
          hint={`Prompts whose stored answers cited competitor-related sources (${intelWindowLabel}). Read the answer to see how they were framed.`}
        />
        <CompetitorPrompts citations={intelCitations} selectedCompetitor={selected} loading={intelLoading} />
      </section>

      {/* 5. Action — ordered and labeled by what THIS page measured, so the
          strongest evidence leads. No signal → the neutral default order. */}
      <section aria-label="Go deeper" className="mb-2">
        <SectionHeader title="Act on the gaps" hint="The analysis views that turn these comparisons into work items." />
        {(() => {
          // Signals already on this page: sources where competitors are cited
          // and you are not (from the citation-overlap table above), and how
          // many configured competitors out-mention you (from the comparison).
          const overlapOnly = intel.sources.filter((s) => s.competitorCitations > 0 && s.brandCitations === 0).length;
          const actions: { href: string; label: React.ReactNode; hasSignal: boolean }[] = [
            {
              href: "/app/ai-intelligence/citation-gaps",
              hasSignal: overlapOnly > 0,
              label:
                overlapOnly > 0
                  ? `Review citation gaps — ${overlapOnly} source${overlapOnly === 1 ? "" : "s"} cite only competitors`
                  : "Citation gaps",
            },
            {
              href: "/app/competitive/insights",
              hasSignal: ahead > 0,
              label:
                ahead > 0
                  ? `Why competitors win — ${ahead} mentioned more often than ${vis.brandName}`
                  : "Competitor insights",
            },
            { href: "/app/competitive/content-gaps", hasSignal: false, label: "Content gaps" },
            {
              href: "/app/competitive/discovery",
              hasSignal: false,
              label: (
                <>
                  Discover more competitors
                  <Badge variant="secondary" className="ml-1">
                    scan
                  </Badge>
                </>
              ),
            },
          ].sort((a, b) => Number(b.hasSignal) - Number(a.hasSignal));
          return (
            <div className="flex flex-wrap gap-2">
              {actions.map((a, i) => (
                <Button key={a.href} asChild size="sm" variant={i === 0 && a.hasSignal ? "default" : "outline"}>
                  <Link href={a.href}>{a.label}</Link>
                </Button>
              ))}
            </div>
          );
        })()}
      </section>

      <SourceDrawer
        row={openSource}
        projectId={current?.id ?? null}
        range={intel.windowRange}
        live={intel.source === "api"}
        mockCitations={intel.raw?.citations ?? []}
        onClose={() => setOpenSource(null)}
      />
    </VisibilityPageFrame>
  );
}
