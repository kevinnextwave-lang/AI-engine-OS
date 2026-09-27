"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
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
  | { kind: "accepting" }
  | { kind: "done"; message: string }
  | { kind: "failed"; message: string };

function AcceptInviteBody() {
  const params = useSearchParams();
  const token = params.get("token");
  const { user, loading } = useAuth();
  const [state, setState] = React.useState<State>(
    token ? { kind: "accepting" } : { kind: "missing" },
  );

  React.useEffect(() => {
    if (!token || loading || !user) return;
    let cancelled = false;
    api.team
      .acceptInvite(token)
      .then((res) => !cancelled && setState({ kind: "done", message: res.message }))
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          kind: "failed",
          message:
            err instanceof ApiError
              ? err.message
              : "Something went wrong. Please open the link again.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [token, loading, user]);

  if (state.kind === "missing") {
    return (
      <p role="alert" className="text-sm">
        This page needs the link from your invitation email. Open the email and click the link
        again.
      </p>
    );
  }
  if (loading) {
    return (
      <p role="status" className="text-muted-foreground text-sm">
        Checking your session…
      </p>
    );
  }
  if (!user) {
    // Accepting requires an account with the INVITED email address; the
    // invite email says the same. After signing in/up, they reopen the link.
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          Sign in with the email address this invitation was sent to, then open the invitation
          link again. New here? Create an account with that address first.
        </p>
        <div className="flex gap-2">
          <Button asChild className="flex-1">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild variant="outline" className="flex-1">
            <Link href="/signup">Create account</Link>
          </Button>
        </div>
      </div>
    );
  }
  if (state.kind === "accepting") {
    return (
      <p role="status" className="text-muted-foreground text-sm">
        Accepting the invitation…
      </p>
    );
  }
  if (state.kind === "failed") {
    return (
      <div className="flex flex-col gap-3">
        <p role="alert" className="text-destructive text-sm">
          {state.message}
        </p>
        <Button asChild variant="outline" className="w-full">
          <Link href="/app">Go to the app</Link>
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p role="status" className="text-sm">
        {state.message} Switch to it from the organization selector in the sidebar.
      </p>
      <Button asChild className="w-full">
        <Link href="/app">Open the app</Link>
      </Button>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <div className="w-full max-w-sm">
      <Card>
        <CardHeader>
          <CardTitle>Team invitation</CardTitle>
          <CardDescription>Joining an organization on AI Search Growth OS.</CardDescription>
        </CardHeader>
        <CardContent>
          {/* useSearchParams requires a Suspense boundary during prerender. */}
          <React.Suspense fallback={null}>
            <AcceptInviteBody />
          </React.Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
