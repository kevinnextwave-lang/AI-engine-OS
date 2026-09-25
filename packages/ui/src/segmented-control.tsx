"use client";

import * as React from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";

import { cn } from "./utils";

/**
 * The one segmented control (time ranges, chart modes). Replaces the three
 * hand-rolled versions. Single-select, always has a value.
 */
function SegmentedControl({
  value,
  onValueChange,
  options,
  className,
  "aria-label": ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: React.ReactNode }[];
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      aria-label={ariaLabel}
      onValueChange={(next) => {
        if (next) onValueChange(next); // ignore deselect — one segment is always active
      }}
      data-slot="segmented-control"
      className={cn("bg-muted inline-flex items-center gap-0.5 rounded-lg p-0.5", className)}
    >
      {options.map((option) => (
        <ToggleGroupPrimitive.Item
          key={option.value}
          value={option.value}
          className={cn(
            "text-muted-foreground rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors",
            "hover:text-foreground focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none",
            "data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:shadow-card",
          )}
        >
          {option.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}

export { SegmentedControl };
