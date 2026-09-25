import Link from "next/link";

import { Button } from "@ai-search-growth-os/ui";

/** Landmarked 404 so assistive tech gets a main region even off the app shell. */
export default function NotFound() {
  return (
    <main className="bg-muted/40 flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-muted-foreground text-sm font-medium tracking-wider uppercase">404</p>
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
        The page you&apos;re looking for doesn&apos;t exist or has moved.
      </p>
      <Button asChild>
        <Link href="/app">Go to dashboard</Link>
      </Button>
    </main>
  );
}
