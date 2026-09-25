/**
 * Open issues by category: horizontal stacked bars from the latest audit's
 * real observation counts, segmented by severity (the same soft severity
 * colors used everywhere). Comparative, current-state data — no history is
 * shown or implied.
 */

import { SEVERITY_LABEL } from "@/lib/geo/labels";
import type { GeoIssue } from "@/lib/geo/types";
import type { Severity } from "@ai-search-growth-os/types";
import { Card, CardContent, Skeleton } from "@ai-search-growth-os/ui";

const SEGMENTS: Array<{ key: Severity; bar: string }> = [
  { key: "critical", bar: "bg-destructive" },
  { key: "high", bar: "bg-warning" },
  { key: "medium", bar: "bg-caution" },
  { key: "low", bar: "bg-info" },
];

export function CategoryBreakdown({ issues, loading }: { issues: GeoIssue[]; loading: boolean }) {
  if (loading) {
    return (
      <Card className="py-4">
        <CardContent className="flex flex-col gap-3 px-4">
          <Skeleton className="h-4 w-44" />
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }
  const open = issues.filter((i) => i.status === "open" && i.severity !== "info");
  if (open.length === 0) return null;

  const byCategory = new Map<string, Partial<Record<Severity, number>>>();
  for (const i of open) {
    const counts = byCategory.get(i.category) ?? {};
    counts[i.severity] = (counts[i.severity] ?? 0) + 1;
    byCategory.set(i.category, counts);
  }
  const rows = [...byCategory.entries()]
    .map(([category, counts]) => ({
      category,
      counts,
      total: Object.values(counts).reduce((a, b) => a + (b ?? 0), 0),
    }))
    .sort((a, b) => b.total - a.total);
  const max = Math.max(1, ...rows.map((r) => r.total));

  return (
    <Card className="py-4">
      <CardContent className="px-4">
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <p className="text-sm font-medium">Open issues by category</p>
          <p className="text-muted-foreground text-xs">{open.length} open · latest audit</p>
        </div>
        <div className="mt-2 flex flex-col gap-2">
          {rows.map((r) => (
            <div key={r.category} className="grid grid-cols-[8.5rem_1fr_2rem] items-center gap-3 text-sm">
              <span className="text-muted-foreground truncate text-xs" title={r.category}>
                {r.category}
              </span>
              <div
                className="bg-muted flex h-2.5 overflow-hidden rounded-full"
                title={SEGMENTS.filter((s) => (r.counts[s.key] ?? 0) > 0)
                  .map((s) => `${r.counts[s.key]} ${SEVERITY_LABEL[s.key].toLowerCase()}`)
                  .join(" · ")}
              >
                {SEGMENTS.map((s) => {
                  const n = r.counts[s.key] ?? 0;
                  if (n === 0) return null;
                  return <div key={s.key} className={s.bar} style={{ width: `${(100 * n) / max}%` }} />;
                })}
              </div>
              <span className="text-right text-xs tabular-nums">{r.total}</span>
            </div>
          ))}
        </div>
        <div className="text-muted-foreground mt-3 flex flex-wrap gap-3 text-xs">
          {SEGMENTS.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className={`size-2 rounded-full ${s.bar}`} aria-hidden="true" />
              {SEVERITY_LABEL[s.key]}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
