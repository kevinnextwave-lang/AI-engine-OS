import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground border-transparent",
        secondary: "bg-secondary text-secondary-foreground border-transparent",
        outline: "text-foreground",
        // Status badges are soft (tinted surface + toned text) — calmer than
        // saturated chips, and every hue comes from the semantic tokens.
        critical: "border-destructive/20 bg-destructive/10 text-destructive",
        high: "border-warning/25 bg-warning/10 text-warning",
        medium: "border-caution/30 bg-caution/10 text-caution",
        low: "border-info/25 bg-info/10 text-info",
        info: "border-info/25 bg-info/10 text-info",
        success: "border-success/25 bg-success/10 text-success",
        muted: "bg-muted text-muted-foreground border-transparent",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
