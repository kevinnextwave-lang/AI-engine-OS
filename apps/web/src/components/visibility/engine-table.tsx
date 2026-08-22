import { ConfidenceBadge } from "@/components/visibility/confidence";
import { fmtValue } from "@/components/visibility/format";
import type { EngineRow } from "@/lib/visibility/types";
import { Progress, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-search-growth-os/ui";

function tone(value: number | null): string {
  if (value == null) return "bg-muted-foreground/40";
  if (value >= 70) return "bg-emerald-600";
  if (value >= 50) return "bg-amber-500";
  return "bg-orange-600";
}

export function EngineTable({
  rows,
  loading,
  detailed = false,
}: {
  rows: EngineRow[];
  loading?: boolean;
  /** Show rates and per-model rows (AI Engines page). */
  detailed?: boolean;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">No AI engine has returned parsed responses in this period.</p>;
  }
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Engine</TableHead>
            <TableHead className="w-44">Visibility</TableHead>
            {detailed && <TableHead className="hidden text-right md:table-cell">Mention</TableHead>}
            {detailed && <TableHead className="hidden text-right md:table-cell">Recommend.</TableHead>}
            {detailed && <TableHead className="hidden text-right lg:table-cell">Citation</TableHead>}
            <TableHead className="text-right">Responses</TableHead>
            <TableHead className="hidden w-40 sm:table-cell">Confidence</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <>
              <TableRow key={r.provider}>
                <TableCell className="font-medium">{r.label}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="w-8 text-right font-semibold tabular-nums">{fmtValue(r.score, "score")}</span>
                    <Progress value={r.score ?? 0} indicatorClassName={tone(r.score)} className="flex-1" aria-label={`${r.label} visibility`} />
                  </div>
                </TableCell>
                {detailed && <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.mentionRate, "percent")}</TableCell>}
                {detailed && <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtValue(r.recommendationRate, "percent")}</TableCell>}
                {detailed && <TableCell className="hidden text-right tabular-nums lg:table-cell">{fmtValue(r.citationRate, "percent")}</TableCell>}
                <TableCell className="text-right tabular-nums">{r.sampleSize}</TableCell>
                <TableCell className="hidden sm:table-cell">
                  <ConfidenceBadge sufficiency={r.sufficiency} sampleSize={r.sampleSize} />
                </TableCell>
              </TableRow>
              {detailed &&
                r.models.map((m) => (
                  <TableRow key={`${r.provider}/${m.model}`} className="text-muted-foreground text-xs">
                    <TableCell className="pl-8 font-mono">{m.model}</TableCell>
                    <TableCell className="tabular-nums">{fmtValue(m.score, "score")}</TableCell>
                    <TableCell className="hidden md:table-cell" />
                    <TableCell className="hidden md:table-cell" />
                    <TableCell className="hidden lg:table-cell" />
                    <TableCell className="text-right tabular-nums">{m.sampleSize}</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <ConfidenceBadge sufficiency={m.sufficiency} sampleSize={m.sampleSize} />
                    </TableCell>
                  </TableRow>
                ))}
            </>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
