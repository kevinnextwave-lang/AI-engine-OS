import { SUFFICIENCY_LABEL } from "@/lib/visibility/labels";
import type { DataQualitySummary } from "@/lib/visibility/types";
import type { Sufficiency } from "@ai-search-growth-os/types";
import { Badge } from "@ai-search-growth-os/ui";

const VARIANT: Record<Sufficiency, "success" | "low" | "medium" | "muted"> = {
  high: "success",
  moderate: "low",
  low: "medium",
  insufficient: "muted",
};

export function ConfidenceBadge({ sufficiency, sampleSize }: { sufficiency: Sufficiency; sampleSize?: number }) {
  return (
    <Badge
      variant={VARIANT[sufficiency]}
      title={
        sampleSize == null
          ? SUFFICIENCY_LABEL[sufficiency]
          : `${SUFFICIENCY_LABEL[sufficiency]} — based on ${sampleSize} AI response${sampleSize === 1 ? "" : "s"}`
      }
    >
      {SUFFICIENCY_LABEL[sufficiency]}
    </Badge>
  );
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "–";
}

/** One line that says exactly what the numbers on the page are based on. */
export function DataBasis({ quality, brandName }: { quality: DataQualitySummary; brandName: string }) {
  return (
    <p className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <ConfidenceBadge sufficiency={quality.sufficiency} sampleSize={quality.sampleSize} />
      <span>
        Measured from <strong className="text-foreground font-medium">{quality.sampleSize}</strong> parsed AI responses to{" "}
        {quality.prompts} prompt{quality.prompts === 1 ? "" : "s"} across {quality.providers} AI engine
        {quality.providers === 1 ? "" : "s"}
        {quality.start ? ` (${fmtDate(quality.start)} – ${fmtDate(quality.end)})` : ""}. Scores are our own AI Visibility
        Score methodology for {brandName}, not an industry standard.
      </span>
    </p>
  );
}
