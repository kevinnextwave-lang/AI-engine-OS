"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { OrganizationProvider } from "@/components/organization-provider";
import { AppShell } from "@/components/shell/app-shell";

/** Auth guard + shell for every route under /app. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading…</p>
      </main>
    );
  }

  return (
    <OrganizationProvider>
      <AppShell>{children}</AppShell>
    </OrganizationProvider>
  );
}
