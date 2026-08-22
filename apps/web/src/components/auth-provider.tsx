"use client";

import * as React from "react";

import { api, refreshSession, setAccessToken, type TokenResponse, type User } from "@/lib/api";

interface AuthContextValue {
  user: User | null;
  /** true until the initial silent refresh has completed */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    full_name?: string;
    organization_name: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    refreshSession().then((session) => {
      if (!cancelled) {
        setUser(session?.user ?? null);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const apply = React.useCallback((session: TokenResponse) => {
    setAccessToken(session.access_token);
    setUser(session.user);
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login: async (email, password) => apply(await api.auth.login({ email, password })),
      register: async (input) => apply(await api.auth.register(input)),
      logout: async () => {
        try {
          await api.auth.logout();
        } finally {
          setAccessToken(null);
          setUser(null);
        }
      },
    }),
    [user, loading, apply],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
