"use client";

/**
 * Simplified AI Search Graph: brand in the centre, competitors around it,
 * prompts on the left arc, sources on the right arc. Edges: mentions
 * (prompt → brand/competitor), cites (prompt → source), associated
 * (brand/competitor ↔ source). Deterministic layout, no physics, no library.
 * Filters narrow the *returned* graph (engine, source type, date) or hide
 * nodes client-side (competitor); the whole graph is never requested.
 */

import * as React from "react";

import { SOURCE_TYPE_LABEL } from "@/lib/intelligence/labels";
import type { GraphView } from "@/lib/intelligence/types";
import { providerLabel } from "@/lib/visibility/labels";
import type { GraphEdge, GraphNode } from "@ai-search-growth-os/types";
import { Card, CardContent, CardHeader, CardTitle, NativeSelect, Skeleton, cn } from "@ai-search-growth-os/ui";

const W = 880;
const H = 520;
const CX = W / 2;
const CY = H / 2;

const NODE_FILL: Record<string, string> = {
  brand: "var(--primary)",
  competitor: "#f59e0b",
  prompt: "#8b5cf6",
  source_domain: "#0ea5e9",
};
const EDGE_STYLE: Record<string, { stroke: string; dash?: string; label: string }> = {
  mentions: { stroke: "#8b5cf6", label: "Mentioned" },
  cites: { stroke: "#0ea5e9", label: "Cited" },
  associated_with: { stroke: "#f59e0b", dash: "4 3", label: "Associated" },
  competes_with: { stroke: "#94a3b8", dash: "2 3", label: "Competes with" },
};
const SHOWN_EDGES = new Set(Object.keys(EDGE_STYLE));
const SHOWN_NODES = new Set(["brand", "competitor", "prompt", "source_domain"]);
const MAX_CITE_EDGES = 36;

interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  r: number;
}

function arc(nodes: GraphNode[], from: number, to: number, radius: number): Placed[] {
  return nodes.map((node, i) => {
    const t = nodes.length === 1 ? (from + to) / 2 : from + ((to - from) * i) / (nodes.length - 1);
    const weight = Number(node.properties.citations ?? node.properties.responses ?? node.properties.mentions ?? 1);
    return { node, x: CX + radius * Math.cos(t), y: CY + radius * Math.sin(t), r: 6 + Math.min(14, Math.sqrt(weight)) };
  });
}

export function layout(view: GraphView, hideCompetitorsExcept: string | null): { placed: Placed[]; edges: GraphEdge[] } {
  const nodes = view.nodes.filter((n) => SHOWN_NODES.has(n.type));
  const brand = nodes.filter((n) => n.type === "brand");
  const competitors = nodes.filter((n) => n.type === "competitor" && (!hideCompetitorsExcept || n.label === hideCompetitorsExcept));
  const prompts = nodes.filter((n) => n.type === "prompt").slice(0, 12);
  const sources = nodes.filter((n) => n.type === "source_domain").slice(0, 14);
  const placed = [
    ...brand.map((node) => ({ node, x: CX, y: CY, r: 22 })),
    ...arc(competitors, -Math.PI / 2 - 0.9, -Math.PI / 2 + 0.9, 120),
    ...arc(prompts, Math.PI / 2 + 0.35, (3 * Math.PI) / 2 - 0.35, 200),
    ...arc(sources, -Math.PI / 2 + 0.35, Math.PI / 2 - 0.35, 210),
  ];
  const ids = new Set(placed.map((p) => p.node.id));
  const all = view.edges.filter((e) => SHOWN_EDGES.has(e.type) && ids.has(e.source) && ids.has(e.target));
  // Simplified: keep every mention/association/competition edge, but only the
  // strongest prompt→source citation edges so the picture stays readable.
  const cites = all.filter((e) => e.type === "cites").sort((a, b) => b.weight - a.weight).slice(0, MAX_CITE_EDGES);
  const edges = [...all.filter((e) => e.type !== "cites"), ...cites];
  return { placed, edges };
}

export function SearchGraph({
  view,
  loading,
  competitors,
  providers,
  sourceTypes,
  filters,
  onFilter,
  onSelectSource,
}: {
  view: GraphView | null;
  loading?: boolean;
  competitors: string[];
  providers: string[];
  sourceTypes: string[];
  filters: { competitor: string | null; sourceType: string | null; provider: string | null };
  onFilter: (f: { competitor?: string | null; sourceType?: string | null; provider?: string | null }) => void;
  onSelectSource?: (sourceDomainId: string) => void;
}) {
  const [hover, setHover] = React.useState<string | null>(null);
  const { placed, edges } = React.useMemo(() => (view ? layout(view, filters.competitor) : { placed: [], edges: [] }), [view, filters.competitor]);
  const pos = new Map(placed.map((p) => [p.node.id, p]));
  const linked = new Set<string>();
  if (hover) {
    for (const e of edges) {
      if (e.source === hover) linked.add(e.target);
      if (e.target === hover) linked.add(e.source);
    }
  }
  const maxWeight = Math.max(1, ...edges.map((e) => e.weight));
  const hovered = hover ? pos.get(hover) : null;

  return (
    <Card className="gap-3 py-5">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 px-5">
        <div>
          <CardTitle className="text-base">AI Search Graph</CardTitle>
          <p className="text-muted-foreground text-xs">Brand, competitors, top prompts and top sources in this period. Hover a node to trace its connections; click a source to open it.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <NativeSelect aria-label="Competitor" className="w-40" value={filters.competitor ?? ""} onChange={(e) => onFilter({ competitor: e.target.value || null })}>
            <option value="">All competitors</option>
            {competitors.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label="Source type" className="w-36" value={filters.sourceType ?? ""} onChange={(e) => onFilter({ sourceType: e.target.value || null })}>
            <option value="">All source types</option>
            {sourceTypes.map((t) => (
              <option key={t} value={t}>
                {SOURCE_TYPE_LABEL[t as keyof typeof SOURCE_TYPE_LABEL] ?? t}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label="AI engine" className="w-36" value={filters.provider ?? ""} onChange={(e) => onFilter({ provider: e.target.value || null })}>
            <option value="">All AI engines</option>
            {providers.map((p) => (
              <option key={p} value={p}>
                {providerLabel(p)}
              </option>
            ))}
          </NativeSelect>
        </div>
      </CardHeader>
      <CardContent className="px-5">
        {loading || !view ? (
          <Skeleton className="h-[26rem] w-full" />
        ) : placed.filter((p) => p.node.type !== "brand").length === 0 ? (
          <div className="text-muted-foreground flex h-64 items-center justify-center rounded-lg border border-dashed text-sm">Nothing to draw for these filters.</div>
        ) : (
          <div className="flex flex-col gap-2">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="AI search graph" onMouseLeave={() => setHover(null)}>
              <text x={CX - 260} y={22} className="fill-muted-foreground text-[11px] font-medium uppercase" textAnchor="middle">
                Prompts
              </text>
              <text x={CX + 260} y={22} className="fill-muted-foreground text-[11px] font-medium uppercase" textAnchor="middle">
                Sources
              </text>
              {edges.map((e, i) => {
                const a = pos.get(e.source)!;
                const b = pos.get(e.target)!;
                const style = EDGE_STYLE[e.type]!;
                const dim = hover !== null && e.source !== hover && e.target !== hover;
                return (
                  <line
                    key={i}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke={style.stroke}
                    strokeDasharray={style.dash}
                    strokeWidth={1 + (3 * e.weight) / maxWeight}
                    strokeOpacity={dim ? 0.08 : 0.55}
                  />
                );
              })}
              {placed.map((p) => {
                const dim = hover !== null && hover !== p.node.id && !linked.has(p.node.id);
                const isSource = p.node.type === "source_domain";
                const left = p.x < CX - 60;
                return (
                  <g
                    key={p.node.id}
                    transform={`translate(${p.x},${p.y})`}
                    opacity={dim ? 0.25 : 1}
                    className={cn(isSource && onSelectSource && "cursor-pointer")}
                    onMouseEnter={() => setHover(p.node.id)}
                    onClick={() => isSource && onSelectSource?.(p.node.id.split(":")[1] ?? "")}
                  >
                    <circle r={p.r} fill={NODE_FILL[p.node.type]} stroke="var(--background)" strokeWidth={2} />
                    <text
                      x={p.node.type === "brand" ? 0 : p.node.type === "competitor" ? 0 : left ? -(p.r + 6) : p.r + 6}
                      y={p.node.type === "brand" ? p.r + 14 : p.node.type === "competitor" ? -(p.r + 6) : 4}
                      textAnchor={p.node.type === "brand" || p.node.type === "competitor" ? "middle" : left ? "end" : "start"}
                      className="fill-foreground text-[11px]"
                    >
                      {p.node.label.length > 34 ? `${p.node.label.slice(0, 32)}…` : p.node.label}
                    </text>
                  </g>
                );
              })}
            </svg>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              {Object.entries(EDGE_STYLE).map(([k, s]) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <svg width="22" height="6" aria-hidden="true">
                    <line x1="0" y1="3" x2="22" y2="3" stroke={s.stroke} strokeWidth="2" strokeDasharray={s.dash} />
                  </svg>
                  <span className="text-muted-foreground">{s.label}</span>
                </span>
              ))}
              {hovered && (
                <span className="ml-auto tabular-nums">
                  <strong>{hovered.node.label}</strong>
                  {" · "}
                  {Object.entries(hovered.node.properties)
                    .filter(([, v]) => typeof v === "number" || typeof v === "string")
                    .slice(0, 4)
                    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`)
                    .join(" · ")}
                </span>
              )}
              {view.truncated && <span className="text-muted-foreground ml-auto">Showing the top nodes only.</span>}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
