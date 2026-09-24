"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  // Signed-in visitors have no business on /login or /signup.
  React.useEffect(() => {
    if (!loading && user) router.replace("/app");
  }, [user, loading, router]);

  return (
    <main className="bg-muted/40 flex min-h-screen flex-col items-center justify-center p-6">
      <div className="mb-6 text-center">
        <h1 className="text-xl font-semibold tracking-tight">AI Search Growth OS</h1>
        <p className="text-muted-foreground text-sm">Visibility across AI search engines</p>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </main>
  );
}
