import Link from "next/link";
import * as React from "react";

/**
 * Public pages reachable from emailed links and legal footers. Unlike the
 * (auth) layout there is deliberately NO signed-in redirect: verification
 * links are usually clicked while signed in (signup keeps the session), and
 * a reset link must work regardless of session state.
 */
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="bg-muted/40 flex min-h-screen flex-col items-center p-6">
      <div className="my-6 text-center">
        <Link href="/" className="text-xl font-semibold tracking-tight">
          AI Search Growth OS
        </Link>
        <p className="text-muted-foreground text-sm">Visibility across AI search engines</p>
      </div>
      {children}
    </main>
  );
}
