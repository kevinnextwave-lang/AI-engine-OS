import type { AuditSummary } from "@/lib/geo/types";
import { Card, CardContent, Skeleton, cn } from "@ai-search-growth-os/ui";

const CELLS: Array<{ key: keyof AuditSummary; label: string; className: string }> = [
  { key: "critical", label: "Critical", className: "text-red-700" },
  { key: "high", label: "High", className: "text-orange-600" },
  { key: "medium", label: "Medium", className: "text-amber-600" },
  { key: "low", label: "Low", className: "text-sky-600" },
  { key: "resolved", label: "Resolved", className: "text-emerald-600" },
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
                <p className={cn("text-2xl font-semibold tabular-nums", cell.className)}>{summary[cell.key]}</p>
              )}
              <p className="text-muted-foreground text-xs">{cell.label}</p>
              <div className="bg-muted h-1.5 overflow-hidden rounded-full">
                <div
                  className={cn("h-full rounded-full", cell.className.replace("text-", "bg-"))}
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
