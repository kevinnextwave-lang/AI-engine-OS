"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { AppSplash } from "@/components/shell/app-splash";
import { OrganizationProvider } from "@/components/organization-provider";
import { ProjectProvider } from "@/components/project-provider";
import { AppShell } from "@/components/shell/app-shell";

/** Auth guard + shell for every route under /app. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) {
    return <AppSplash />;
  }

  return (
    <OrganizationProvider>
      {/* One ProjectProvider for the whole app: the project list is fetched
          once per organization instead of once per section, so crossing a
          section boundary no longer refetches or flashes loading state. */}
      <ProjectProvider>
        <AppShell>{children}</AppShell>
      </ProjectProvider>
    </OrganizationProvider>
  );
}
