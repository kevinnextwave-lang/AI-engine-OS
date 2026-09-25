"use client";

import { AlertTriangleIcon } from "lucide-react";

import { Button } from "@ai-search-growth-os/ui";

/** THE load-failure box: what failed, the actual error, and a retry. */
export function LoadError({ what, message, onRetry }: { what: string; message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="border-destructive/40 bg-destructive/5 flex flex-col items-start gap-3 rounded-xl border p-5 text-sm"
    >
      <p className="flex items-center gap-2 font-medium">
        <AlertTriangleIcon className="text-destructive size-4" aria-hidden="true" />
        Could not load {what}
      </p>
      <p className="text-muted-foreground">{message}</p>
      <Button size="sm" variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
