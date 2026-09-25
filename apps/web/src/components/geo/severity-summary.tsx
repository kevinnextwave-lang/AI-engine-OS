import type { AuditSummary } from "@/lib/geo/types";
import { Card, CardContent, Skeleton, cn } from "@ai-search-growth-os/ui";

// Explicit text+bar classes (never string-built at runtime: Tailwind only
// generates classes it can see in the source — the old .replace() trick left
// the Medium bar invisible).
const CELLS: Array<{ key: keyof AuditSummary; label: string; text: string; bar: string }> = [
  { key: "critical", label: "Critical", text: "text-destructive", bar: "bg-destructive" },
  { key: "high", label: "High", text: "text-warning", bar: "bg-warning" },
  { key: "medium", label: "Medium", text: "text-caution", bar: "bg-caution" },
  { key: "low", label: "Low", text: "text-info", bar: "bg-info" },
  { key: "resolved", label: "Resolved", text: "text-success", bar: "bg-success" },
];

export function SeveritySummary({ summary, loading }: { summary: AuditSummary; loading?: boolean }) {
  const open = summary.critical + summary.high + summary.medium + summary.low;
  const max = Math.max(1, ...CELLS.map((c) => summary[c.key]));
  return (
    <Card className="py-5">
      <CardContent className="px-5">
        <div className="mb-4 flex items-baseline justify-between">
          <p className="text-sm font-medium">Audit summary</p>
          <p className="text-muted-foreground text-xs">
            {loading ? "" : `${open} open · ${summary.info} informational`}
          </p>
        </div>
        <div className="grid grid-cols-5 gap-3">
          {CELLS.map((cell) => (
            <div key={cell.key} className="flex flex-col gap-2">
              {loading ? (
                <Skeleton className="h-8 w-10" />
              ) : (
                <p className={cn("text-2xl font-semibold tabular-nums", cell.text)}>{summary[cell.key]}</p>
              )}
              <p className="text-muted-foreground text-xs">{cell.label}</p>
              <div className="bg-muted h-1.5 overflow-hidden rounded-full">
                <div
                  className={cn("h-full rounded-full", cell.bar)}
                  style={{ width: loading ? "0%" : `${(100 * summary[cell.key]) / max}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
