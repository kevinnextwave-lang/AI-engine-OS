"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { TeamCard } from "@/components/settings/team-card";
import { PageHeader } from "@/components/shell/page-header";
import { ApiError, api, type BillingSummary } from "@/lib/api";
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

  // Plan & billing summary for the current organization.
  const [billingState, setBillingState] = React.useState<{
    orgId: string;
    data: BillingSummary;
  } | null>(null);
  const [billingBusy, setBillingBusy] = React.useState(false);
  const [billingError, setBillingError] = React.useState<string | null>(null);
  const orgId = current?.id ?? null;
  React.useEffect(() => {
    if (!orgId) return;
    let cancelled = false;
    api.billing
      .summary(orgId)
      .then((data) => !cancelled && setBillingState({ orgId, data }))
      .catch(() => !cancelled && setBillingState(null));
    return () => {
      cancelled = true;
    };
  }, [orgId]);
  const billing = billingState?.orgId === orgId ? billingState.data : null;

  // Weekly digest preference: optimistic local override until the provider
  // refetches; the server value from the org list is the baseline.
  const canManageOrg = current?.role === "owner" || current?.role === "admin";
  const [digestPref, setDigestPref] = React.useState<{ orgId: string; value: boolean } | null>(
    null,
  );
  const [digestBusy, setDigestBusy] = React.useState(false);
  const [digestError, setDigestError] = React.useState<string | null>(null);
  const digestEnabled =
    digestPref?.orgId === orgId ? digestPref.value : (current?.weekly_digest_enabled ?? true);

  async function saveDigestPref(value: boolean) {
    if (!orgId) return;
    setDigestBusy(true);
    setDigestError(null);
    const previous = digestEnabled;
    setDigestPref({ orgId, value });
    try {
      await api.organizations.update(orgId, { weekly_digest_enabled: value });
    } catch (err) {
      setDigestPref({ orgId, value: previous });
      setDigestError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setDigestBusy(false);
    }
  }

  async function openBilling(target: "starter" | "growth" | "portal") {
    if (!orgId) return;
    setBillingBusy(true);
    setBillingError(null);
    try {
      const { url } =
        target === "portal"
          ? await api.billing.portal(orgId)
          : await api.billing.checkout(orgId, target);
      window.location.href = url; // external Stripe-hosted page
    } catch (err) {
      setBillingError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
      setBillingBusy(false);
    }
  }
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
            <div className="flex items-start gap-2 pt-1">
              <input
                id="org-digest"
                type="checkbox"
                className="accent-primary mt-0.5 size-4"
                checked={digestEnabled}
                disabled={!canManageOrg || digestBusy}
                onChange={(e) => void saveDigestPref(e.target.checked)}
              />
              <div className="grid gap-0.5">
                <Label htmlFor="org-digest">Weekly digest email</Label>
                <p className="text-muted-foreground text-xs">
                  Monday summary of visibility movement, collections, and audits — sent to
                  owners and admins. {digestError ?? ""}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <TeamCard />

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Plan & billing</CardTitle>
          <CardDescription>
            Usage limits come from the organization&apos;s plan; the AI budget resets at midnight
            UTC.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!billing ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : (
            <div className="flex flex-col gap-3">
              {billing.status === "suspended" && (
                <p role="alert" className="text-destructive text-sm font-medium">
                  This organization is on a billing hold — access is paused until payment is
                  fixed via “Manage billing”.
                </p>
              )}
              <p className="text-sm">
                Current plan: <span className="font-semibold">{billing.plan_label}</span>
                <span className="text-muted-foreground">
                  {" "}
                  · AI usage today ${billing.ai_spend_today_usd.toFixed(2)} of $
                  {billing.limits.ai_daily_cost_usd.toFixed(2)}
                </span>
              </p>
              <p className="text-muted-foreground text-xs">
                {billing.limits.projects_per_org ?? "Unlimited"} project
                {billing.limits.projects_per_org === 1 ? "" : "s"} ·{" "}
                {billing.limits.prompts_per_batch} prompts per run ·{" "}
                {billing.limits.seo_audits_per_month == null
                  ? "unlimited audits"
                  : `${billing.limits.seo_audits_per_month} audits/month`}
              </p>
              {billing.can_manage && billing.billing_enabled && (
                <div className="flex flex-wrap gap-2">
                  {billing.has_subscription ? (
                    <Button variant="outline" onClick={() => openBilling("portal")} disabled={billingBusy}>
                      Manage billing
                    </Button>
                  ) : (
                    <>
                      <Button onClick={() => openBilling("starter")} disabled={billingBusy}>
                        Upgrade to Starter
                      </Button>
                      <Button variant="outline" onClick={() => openBilling("growth")} disabled={billingBusy}>
                        Upgrade to Growth
                      </Button>
                    </>
                  )}
                </div>
              )}
              {billing.can_manage && !billing.billing_enabled && (
                <p className="text-muted-foreground text-xs">
                  Self-serve upgrades aren&apos;t configured on this deployment yet.
                </p>
              )}
              {billingError && (
                <p role="alert" className="text-destructive text-sm">
                  {billingError}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

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
