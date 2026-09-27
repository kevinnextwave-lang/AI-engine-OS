"use client";

import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { ApiError, api, type Member, type OrgInvite } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  NativeSelect,
} from "@ai-search-growth-os/ui";

/**
 * Team management for the current organization: members with roles, email
 * invitations, removal. The API is the authority on every rule (owner-only
 * operations, last-owner protection, email-matched accepts) — this card
 * just surfaces its answers honestly.
 */
export function TeamCard() {
  const { user } = useAuth();
  const { current } = useOrganization();
  const orgId = current?.id ?? null;
  const canManage = current?.role === "owner" || current?.role === "admin";

  const [state, setState] = React.useState<{
    orgId: string;
    members: Member[];
    invites: OrgInvite[];
  } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [inviteEmail, setInviteEmail] = React.useState("");
  const [inviteRole, setInviteRole] = React.useState("member");
  const [notice, setNotice] = React.useState<string | null>(null);

  const load = React.useCallback(async (org: string, manage: boolean) => {
    const [members, invites] = await Promise.all([
      api.organizations.members(org),
      manage ? api.team.invites(org) : Promise.resolve([]),
    ]);
    return { orgId: org, members, invites };
  }, []);

  React.useEffect(() => {
    if (!orgId) return;
    let cancelled = false;
    load(orgId, canManage)
      .then((next) => !cancelled && setState(next))
      .catch(() => !cancelled && setState(null));
    return () => {
      cancelled = true;
    };
  }, [orgId, canManage, load]);

  const data = state?.orgId === orgId ? state : null;

  async function run(action: () => Promise<unknown>, successNotice?: string) {
    if (!orgId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setState(await load(orgId, canManage));
      if (successNotice) setNotice(successNotice);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onInvite(e: React.FormEvent) {
    e.preventDefault();
    const email = inviteEmail;
    await run(
      () => api.team.invite(orgId!, { email, role: inviteRole }),
      `Invitation sent to ${email}.`,
    );
    setInviteEmail("");
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Team</CardTitle>
        <CardDescription>
          Who has access to this organization. Invitations are emailed, valid for 7 days, and can
          only be accepted by an account with the invited address.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!data ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : (
          <>
            <ul className="flex flex-col divide-y text-sm">
              {data.members.map((m) => {
                const isSelf = m.user_id === user?.id;
                return (
                  <li key={m.user_id} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{m.full_name ?? m.email}</span>{" "}
                      <span className="text-muted-foreground">
                        {m.full_name ? `· ${m.email}` : ""}
                        {isSelf ? " (you)" : ""}
                      </span>
                    </span>
                    {canManage && !isSelf ? (
                      <NativeSelect
                        aria-label={`Role for ${m.email}`}
                        value={m.role}
                        disabled={busy}
                        className="w-28"
                        onChange={(e) =>
                          run(
                            () => api.team.changeRole(orgId!, m.user_id, e.target.value),
                            "Role updated.",
                          )
                        }
                      >
                        <option value="viewer">Viewer</option>
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                        <option value="owner">Owner</option>
                      </NativeSelect>
                    ) : (
                      <Badge variant="outline" className="capitalize">
                        {m.role}
                      </Badge>
                    )}
                    {(canManage || isSelf) && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () => api.team.removeMember(orgId!, m.user_id),
                            isSelf ? "You left the organization." : "Member removed.",
                          )
                        }
                      >
                        {isSelf ? "Leave" : "Remove"}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>

            {canManage && data.invites.length > 0 && (
              <div>
                <p className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
                  Pending invitations
                </p>
                <ul className="mt-1 flex flex-col divide-y text-sm">
                  {data.invites.map((inv) => (
                    <li key={inv.id} className="flex items-center gap-2 py-2">
                      <span className="min-w-0 flex-1 truncate">{inv.email}</span>
                      <Badge variant="outline" className="capitalize">
                        {inv.role}
                      </Badge>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () => api.team.revokeInvite(orgId!, inv.id),
                            "Invitation revoked.",
                          )
                        }
                      >
                        Revoke
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {canManage && (
              <form onSubmit={onInvite} className="flex flex-wrap items-end gap-2">
                <div className="grid min-w-56 flex-1 gap-2">
                  <Label htmlFor="invite-email">Invite by email</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    required
                    placeholder="teammate@company.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="invite-role">Role</Label>
                  <NativeSelect
                    id="invite-role"
                    value={inviteRole}
                    className="w-32"
                    onChange={(e) => setInviteRole(e.target.value)}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </NativeSelect>
                </div>
                <Button type="submit" disabled={busy || !inviteEmail}>
                  Send invite
                </Button>
              </form>
            )}

            {notice && (
              <p role="status" className="text-sm">
                {notice}
              </p>
            )}
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
