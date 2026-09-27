"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { ApiError, api } from "@/lib/api";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@ai-search-growth-os/ui";

type State =
  | { kind: "missing" }
  | { kind: "verifying" }
  | { kind: "done" }
  | { kind: "failed"; message: string };

function VerifyEmailBody() {
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = React.useState<State>(
    token ? { kind: "verifying" } : { kind: "missing" },
  );

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api.auth
      .verifyEmail(token)
      .then(() => !cancelled && setState({ kind: "done" }))
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          kind: "failed",
          message:
            err instanceof ApiError
              ? err.message
              : "Something went wrong. Please try the link again.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state.kind === "missing") {
    return (
      <p role="alert" className="text-sm">
        This page needs the link from your verification email. Open the email and click the link
        again.
      </p>
    );
  }
  if (state.kind === "verifying") {
    return (
      <p role="status" className="text-muted-foreground text-sm">
        Verifying your email address…
      </p>
    );
  }
  if (state.kind === "failed") {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-destructive text-sm">
          {state.message}
        </p>
        <p className="text-muted-foreground text-sm">
          You can request a fresh link from Settings once signed in.
        </p>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Go to sign in</Link>
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-sm">
        Your email address is verified. You&apos;re all set.
      </p>
      <Button asChild className="w-full">
        <Link href="/app">Open the app</Link>
      </Button>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="w-full max-w-sm">
    <Card>
      <CardHeader>
        <CardTitle>Email verification</CardTitle>
        <CardDescription>Confirming the address on your account.</CardDescription>
      </CardHeader>
      <CardContent>
        {/* useSearchParams requires a Suspense boundary during prerender. */}
        <React.Suspense fallback={null}>
          <VerifyEmailBody />
        </React.Suspense>
      </CardContent>
    </Card>
    </div>
  );
}
