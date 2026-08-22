/**
 * Typed API client.
 *
 * - Access token lives in memory only (never localStorage).
 * - Refresh token is an httpOnly cookie managed by the API; we just send
 *   `credentials: "include"` and call /auth/refresh when a 401 comes back.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export type MembershipRole = "owner" | "admin" | "member" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: MembershipRole;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string | null;
  role: MembershipRole;
  joined_at: string;
}

let accessToken: string | null = null;
let refreshInFlight: Promise<TokenResponse | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | undefined;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }
  return new ApiError(
    res.status,
    body?.error?.code ?? "unknown_error",
    body?.error?.message ?? `Request failed with status ${res.status}`,
    body?.error?.details,
  );
}

async function rawRequest<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth && accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${API_URL}${API_PREFIX}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Attempt to mint a new access token from the refresh cookie. Deduplicated. */
export async function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = rawRequest<TokenResponse>("/auth/refresh", { method: "POST" }, false)
      .then((data) => {
        accessToken = data.access_token;
        return data;
      })
      .catch(() => {
        accessToken = null;
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/** Authenticated request with one transparent refresh-and-retry on 401. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, init);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshSession();
      if (refreshed) return rawRequest<T>(path, init);
    }
    throw err;
  }
}

export const api = {
  auth: {
    register: (body: {
      email: string;
      password: string;
      full_name?: string;
      organization_name: string;
    }) =>
      rawRequest<TokenResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) }, false),
    login: (body: { email: string; password: string }) =>
      rawRequest<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) }, false),
    logout: () => rawRequest<{ message: string }>("/auth/logout", { method: "POST" }, false),
    me: () => request<User>("/auth/me"),
  },
  organizations: {
    list: () => request<Organization[]>("/organizations"),
    create: (body: { name: string }) =>
      request<Organization>("/organizations", { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) => request<Organization>(`/organizations/${id}`),
    members: (id: string) => request<Member[]>(`/organizations/${id}/members`),
  },
};
