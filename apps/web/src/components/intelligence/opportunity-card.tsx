import { CONFIDENCE_LABEL } from "@/lib/intelligence/labels";
import type { OpportunityCard as Card_ } from "@/lib/intelligence/types";
import { Badge, Button, Card, CardContent, cn } from "@ai-search-growth-os/ui";

const PRIORITY_VARIANT = { high: "high", medium: "medium", low: "muted" } as const;

export function OpportunityCard({ card, onOpen }: { card: Card_; onOpen: (gapId: string) => void }) {
  const g = card.gap;
  return (
    <Card className="gap-3 py-4">
      <CardContent className="flex flex-col gap-3 px-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-semibold">{g.display_name}</p>
            <Badge variant={PRIORITY_VARIANT[g.priority]} className="mt-1 uppercase">
              {card.priorityLabel}
            </Badge>
          </div>
          <span className="text-right">
            <span className="text-muted-foreground block text-[11px] uppercase">Opportunity score</span>
            <span className="text-2xl font-semibold tabular-nums">{Math.round(g.opportunity_score)}</span>
          </span>
        </div>
        <ul className="flex flex-col gap-1 text-sm">
          {card.rows.map((r) => (
            <li key={r.name} className={cn("flex justify-between tabular-nums", r.isBrand && "border-t pt-1 font-medium")}>
              <span className="truncate">{r.isBrand ? "Your brand" : r.name}</span>
              <span>{r.citations} citation{r.citations === 1 ? "" : "s"}</span>
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground text-xs" title={g.explanation}>
          {CONFIDENCE_LABEL[g.confidence]} · {g.relevant_response_count} responses
        </p>
        <Button size="sm" variant="outline" onClick={() => onOpen(g.id)}>
          View opportunity
        </Button>
      </CardContent>
    </Card>
  );
}
