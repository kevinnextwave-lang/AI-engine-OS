"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/shell/page-header";
import { ApiError, api } from "@/lib/api";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@ai-search-growth-os/ui";

export default function SettingsPage() {
  const { user } = useAuth();
  const { current, loading: orgLoading, error: orgError } = useOrganization();
  const router = useRouter();
  const orgPlaceholder = orgLoading ? "Loading…" : "—";

  const [resendState, setResendState] = React.useState<"idle" | "sending" | "sent">("idle");
  const [confirming, setConfirming] = React.useState(false);
  const [deletePassword, setDeletePassword] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  async function resendVerification() {
    setResendState("sending");
    try {
      await api.auth.resendVerification();
      setResendState("sent");
    } catch {
      setResendState("idle");
    }
  }

  async function onDeleteAccount(e: React.FormEvent) {
    e.preventDefault();
    setDeleteError(null);
    setDeleting(true);
    try {
      await api.auth.deleteAccount(deletePassword);
      // The account (and its sessions) no longer exist; leave client state behind.
      router.replace("/login");
    } catch (err) {
      setDeleteError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader title="Settings" description="Your profile and the current organization." />
      {orgError && (
        <p role="alert" className="text-destructive mb-4 text-sm">
          {orgError}
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Editing arrives with account management in a later milestone.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="profile-first-name">First name</Label>
                <Input id="profile-first-name" readOnly value={user?.first_name ?? ""} placeholder="—" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="profile-last-name">Last name</Label>
                <Input id="profile-last-name" readOnly value={user?.last_name ?? ""} placeholder="—" />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-email">Email</Label>
              <Input id="profile-email" readOnly value={user?.email ?? ""} />
              {user && !user.email_verified && (
                <p className="text-muted-foreground text-xs">
                  Not verified yet.{" "}
                  <button
                    type="button"
                    onClick={resendVerification}
                    disabled={resendState === "sending"}
                    className="text-foreground underline underline-offset-4 disabled:opacity-60"
                  >
                    {resendState === "sent" ? "Sent — check your inbox" : "Resend verification email"}
                  </button>
                </p>
              )}
              {user?.email_verified && (
                <p className="text-muted-foreground text-xs">Verified.</p>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Organization</CardTitle>
            <CardDescription>Switch organizations from the sidebar selector.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="org-name">Name</Label>
              <Input id="org-name" readOnly value={current?.name ?? ""} placeholder={orgPlaceholder} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="org-slug">Slug</Label>
              <Input id="org-slug" readOnly className="font-mono" value={current?.slug ?? ""} placeholder={orgPlaceholder} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="org-role">Your role</Label>
              <Input id="org-role" readOnly className="capitalize" value={current?.role ?? ""} placeholder={orgPlaceholder} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-destructive/40 mt-4">
        <CardHeader>
          <CardTitle>Danger zone</CardTitle>
          <CardDescription>
            Deleting your account is permanent. Organizations where you are the only member are
            deleted with it; one with other members needs another owner first.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!confirming ? (
            <Button variant="outline" className="text-destructive" onClick={() => setConfirming(true)}>
              Delete account…
            </Button>
          ) : (
            <form onSubmit={onDeleteAccount} className="flex max-w-sm flex-col gap-3">
              <div className="grid gap-2">
                <Label htmlFor="delete-password">Confirm with your password</Label>
                <Input
                  id="delete-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={deletePassword}
                  onChange={(e) => setDeletePassword(e.target.value)}
                />
              </div>
              {deleteError && (
                <p role="alert" className="text-destructive text-sm">
                  {deleteError}
                </p>
              )}
              <div className="flex gap-2">
                <Button type="submit" variant="destructive" disabled={deleting}>
                  {deleting ? "Deleting…" : "Permanently delete my account"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setConfirming(false);
                    setDeletePassword("");
                    setDeleteError(null);
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </>
  );
}
