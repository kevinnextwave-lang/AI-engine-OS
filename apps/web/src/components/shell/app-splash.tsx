/**
 * Full-page loading gate shown while the session/authentication resolves.
 * Branded and honest: no progress is claimed, because none is reported.
 */
export function AppSplash() {
  return (
    <main className="flex min-h-screen items-center justify-center" role="status" aria-label="Loading">
      <div className="flex animate-pulse items-center gap-2.5">
        <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-md text-xs font-semibold">
          AI
        </span>
        <span className="text-muted-foreground text-sm">Loading your workspace…</span>
      </div>
    </main>
  );
}
