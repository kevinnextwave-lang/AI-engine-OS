"use client";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/shell/page-header";
import {
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
  const { current } = useOrganization();

  return (
    <>
      <PageHeader title="Settings" description="Your profile and the current organization." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Editing arrives with account management in a later milestone.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="profile-name">Full name</Label>
              <Input id="profile-name" readOnly value={user?.full_name ?? ""} placeholder="—" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-email">Email</Label>
              <Input id="profile-email" readOnly value={user?.email ?? ""} />
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
              <Input id="org-name" readOnly value={current?.name ?? ""} placeholder="—" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="org-slug">Slug</Label>
              <Input id="org-slug" readOnly className="font-mono" value={current?.slug ?? ""} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="org-role">Your role</Label>
              <Input id="org-role" readOnly className="capitalize" value={current?.role ?? ""} />
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
