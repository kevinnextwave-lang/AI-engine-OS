import * as React from "react";

import { cn } from "./utils";

/** Initials avatar — no image dependency, good enough until profile photos exist. */
function Avatar({
  name,
  className,
  ...props
}: React.ComponentProps<"span"> & { name: string }) {
  const initials = name
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <span
      data-slot="avatar"
      aria-hidden="true"
      className={cn(
        "bg-primary text-primary-foreground inline-flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold select-none",
        className,
      )}
      {...props}
    >
      {initials || "?"}
    </span>
  );
}

export { Avatar };
