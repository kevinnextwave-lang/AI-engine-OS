"use client";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/shell/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@ai-search-growth-os/ui";

export default function OverviewPage() {
  const { user } = useAuth();
  const { current, organizations, loading, error } = useOrganization();

  return (
    <>
      <PageHeader
        title={`Welcome${user?.full_name ? `, ${user.full_name}` : ""}`}
        description="Milestone 1 foundation. AI visibility monitoring and the rest of the product arrive in upcoming milestones."
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Current organization</CardTitle>
            <CardDescription>Selected in the sidebar; every resource is scoped to it.</CardDescription>
          </CardHeader>
          <CardContent>
            {error && <p className="text-destructive text-sm">{error}</p>}
            {!error && loading && <p className="text-muted-foreground text-sm">Loading…</p>}
            {!error && !loading && current && (
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">{current.name}</p>
                  <p className="text-muted-foreground font-mono text-xs">{current.slug}</p>
                </div>
                <span className="bg-secondary text-secondary-foreground rounded-md px-2 py-1 text-xs font-medium capitalize">
                  {current.role}
                </span>
              </div>
            )}
            {!error && !loading && !current && (
              <p className="text-muted-foreground text-sm">You don&apos;t belong to any organizations yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Memberships</CardTitle>
            <CardDescription>Organizations you can switch between.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{loading ? "–" : organizations.length}</p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
