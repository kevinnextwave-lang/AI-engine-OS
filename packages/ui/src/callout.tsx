import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  InfoIcon,
  OctagonAlertIcon,
} from "lucide-react";

import { cn } from "./utils";

const calloutVariants = cva("flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm", {
  variants: {
    variant: {
      info: "border-info/25 bg-info/5 text-foreground",
      success: "border-success/25 bg-success/5 text-foreground",
      warning: "border-caution/30 bg-caution/8 text-foreground",
      error: "border-destructive/25 bg-destructive/5 text-foreground",
      // Provenance notice: the data on screen is sample data, not the user's.
      sample: "border-caution/30 bg-caution/8 text-foreground",
    },
  },
  defaultVariants: { variant: "info" },
});

const ICONS = {
  info: InfoIcon,
  success: CheckCircle2Icon,
  warning: AlertTriangleIcon,
  error: OctagonAlertIcon,
  sample: DatabaseIcon,
} as const;

const ICON_TONE = {
  info: "text-info",
  success: "text-success",
  warning: "text-caution",
  error: "text-destructive",
  sample: "text-caution",
} as const;

/**
 * The one inline notice. Replaces the hand-rolled MockNotice, error boxes,
 * hold-reason banners and insufficient-data notes. `error` calls out failures
 * (pass `action` for a Retry button); `sample` marks sample data.
 */
function Callout({
  className,
  variant = "info",
  title,
  action,
  children,
  ...props
}: React.ComponentProps<"div"> &
  VariantProps<typeof calloutVariants> & {
    title?: React.ReactNode;
    action?: React.ReactNode;
  }) {
  const Icon = ICONS[variant ?? "info"];
  return (
    <div
      data-slot="callout"
      role={variant === "error" ? "alert" : "status"}
      className={cn(calloutVariants({ variant }), className)}
      {...props}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", ICON_TONE[variant ?? "info"])} aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className="text-muted-foreground [&_p]:leading-relaxed">{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export { Callout, calloutVariants };
