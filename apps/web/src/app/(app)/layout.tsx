"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
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
    <div className="flex min-h-screen flex-col">
      <header className="flex h-14 items-center justify-between border-b px-6">
        <span className="font-semibold tracking-tight">AI Search Growth OS</span>
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground hidden text-sm sm:inline">{user.email}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
          >
            Sign out
          </Button>
        </div>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
