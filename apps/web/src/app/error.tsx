"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@ai-search-growth-os/ui";

/**
 * Route-level error boundary: an unexpected render/runtime error shows an
 * honest recovery screen instead of a blank page. Next.js logs the error
 * to the console; the digest is surfaced so support can correlate it.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();
  return (
    <main className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-xl font-semibold tracking-tight">Something went wrong</h1>
      <p className="text-muted-foreground max-w-md text-sm">
        The page hit an unexpected error. Your data is fine — try again, and if it keeps
        happening, reload the app{error.digest ? ` and mention error ${error.digest}` : ""}.
      </p>
      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button variant="outline" onClick={() => router.push("/app")}>
          Back to overview
        </Button>
      </div>
    </main>
  );
}
