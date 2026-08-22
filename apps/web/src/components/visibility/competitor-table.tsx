import { fmtValue } from "@/components/visibility/format";
import type { CompetitorShareRow } from "@/lib/visibility/types";
import { Badge, Progress, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, cn } from "@ai-search-growth-os/ui";

export function CompetitorTable({
  rows,
  loading,
  detailed = false,
  competitorsConfigured,
}: {
  rows: CompetitorShareRow[];
  loading?: boolean;
  detailed?: boolean;
  competitorsConfigured: number;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (competitorsConfigured === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No competitors are configured for this project. Add them in project settings to compare measured mention rates.
      </p>
    );
  }
  const sorted = [...rows].sort((a, b) => (b.mentionRate ?? -1) - (a.mentionRate ?? -1));
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Brand</TableHead>
            <TableHead className="w-52">Mention rate</TableHead>
            {detailed && <TableHead className="hidden text-right md:table-cell">Share of voice</TableHead>}
            {detailed && <TableHead className="hidden text-right md:table-cell">Recommended</TableHead>}
            {detailed && <TableHead className="hidden text-right lg:table-cell">Avg. position</TableHead>}
            {detailed && <TableHead className="hidden text-right lg:table-cell">Sentiment</TableHead>}
            <TableHead className="text-right">Mentions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((r) => (
            <TableRow key={r.name} className={cn(r.isBrand && "bg-primary/5")}>
              <TableCell className="font-medium">
                <span className="flex items-center gap-2">
                  {r.name}
                  {r.isBrand && <Badge variant="outline">You</Badge>}
                </span>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <span className="w-11 text-right font-semibold tabular-nums">{fmtValue(r.mentionRate, "percent")}</span>
                  <Progress
                    value={r.mentionRate ?? 0}
                    indicatorClassName={r.isBrand ? "bg-primary" : "bg-muted-foreground/60"}
                    className="flex-1"
                    aria-label={`${r.name} mention rate`}
                  />
                </div>
              </TableCell>
              {detailed && <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.shareOfVoice, "percent")}</TableCell>}
              {detailed && <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.recommendationRate, "percent")}</TableCell>}
              {detailed && <TableCell className="hidden text-right tabular-nums lg:table-cell">{fmtValue(r.averagePosition, "position")}</TableCell>}
              {detailed && (
                <TableCell className="hidden text-right tabular-nums lg:table-cell">
                  {r.sentimentScore == null ? "–" : `${Math.round(r.sentimentScore)}/100`}
                </TableCell>
              )}
              <TableCell className="text-right tabular-nums">{r.mentions}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
