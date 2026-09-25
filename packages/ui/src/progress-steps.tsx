import * as React from "react";
import { CheckIcon, CircleIcon, Loader2Icon, XIcon } from "lucide-react";

import { cn } from "./utils";

/**
 * THE live-progress pattern for long-running operations (crawls, audits,
 * agent workflows). Every step's status must come from the backend — a step
 * is never advanced client-side, and details (counts, timings) are shown
 * only when the backend reports them. When no real progress exists, callers
 * use a plain honest loading state instead of this component.
 */

export type ProgressStepStatus = "done" | "active" | "pending" | "failed";

export interface ProgressStep {
  label: React.ReactNode;
  status: ProgressStepStatus;
  /** Real reported detail, e.g. "12 crawled · 15 discovered". */
  detail?: React.ReactNode;
}

function StepIcon({ status }: { status: ProgressStepStatus }) {
  if (status === "done") return <CheckIcon className="text-success size-4 shrink-0" aria-hidden="true" />;
  if (status === "active") return <Loader2Icon className="text-primary size-4 shrink-0 animate-spin" aria-hidden="true" />;
  if (status === "failed") return <XIcon className="text-destructive size-4 shrink-0" aria-hidden="true" />;
  return <CircleIcon className="text-muted-foreground/60 size-4 shrink-0" aria-hidden="true" />;
}

const STATUS_TEXT: Record<ProgressStepStatus, string> = {
  done: "Completed",
  active: "In progress",
  pending: "Waiting",
  failed: "Failed",
};

function ProgressSteps({
  title,
  steps,
  note,
  className,
}: {
  /** What is running, e.g. "Running GEO audit". */
  title?: React.ReactNode;
  steps: ProgressStep[];
  /** One honest footnote, e.g. "Updates automatically every few seconds." */
  note?: React.ReactNode;
  className?: string;
}) {
  return (
    // fade-in marks the block appearing when an operation starts reporting.
    <div data-slot="progress-steps" role="status" className={cn("animate-in fade-in flex flex-col gap-2 duration-300", className)}>
      {title && <p className="text-sm font-medium">{title}</p>}
      <ol className="flex flex-col gap-1.5">
        {steps.map((step, i) => (
          <li key={i} className="flex items-center gap-2.5 text-sm">
            <StepIcon status={step.status} />
            <span className={cn(step.status === "pending" && "text-muted-foreground")}>{step.label}</span>
            <span className="sr-only">: {STATUS_TEXT[step.status]}</span>
            {step.detail && <span className="text-muted-foreground ml-auto text-xs tabular-nums">{step.detail}</span>}
          </li>
        ))}
      </ol>
      {note && <p className="text-muted-foreground text-xs">{note}</p>}
    </div>
  );
}

export { ProgressSteps };
