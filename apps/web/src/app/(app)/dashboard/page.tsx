"use client";

import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type Organization } from "@/lib/api";

export default function DashboardPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = React.useState<Organization[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api.organizations
      .list()
      .then(setOrgs)
      .catch(() => setError("Could not load your organizations."));
  }, []);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome{user?.full_name ? `, ${user.full_name}` : ""}
        </h1>
        <p className="text-muted-foreground text-sm">
          Milestone 1 foundation is live. Monitoring modules arrive in the next milestones.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your organizations</CardTitle>
          <CardDescription>Workspaces you belong to and your role in each.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <p className="text-destructive text-sm">{error}</p>}
          {!error && orgs === null && <p className="text-muted-foreground text-sm">Loading…</p>}
          {orgs && orgs.length === 0 && (
            <p className="text-muted-foreground text-sm">You don&apos;t belong to any organizations yet.</p>
          )}
          {orgs && orgs.length > 0 && (
            <ul className="divide-y">
              {orgs.map((org) => (
                <li key={org.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="font-medium">{org.name}</p>
                    <p className="text-muted-foreground font-mono text-xs">{org.slug}</p>
                  </div>
                  <span className="bg-secondary text-secondary-foreground rounded-md px-2 py-1 text-xs font-medium capitalize">
                    {org.role}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
