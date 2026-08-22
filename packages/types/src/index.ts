/**
 * Shared API contract types. Keep in sync with apps/api/app/schemas/*.
 * Dates are ISO-8601 UTC strings; ids are UUIDs.
 */

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export interface User {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  /** Derived server-side from first_name + last_name. */
  full_name: string | null;
  is_active: boolean;
  email_verified: boolean;
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

export interface RegisterRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  organization_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type ProjectStatus = "active" | "paused" | "archived";

export interface Domain {
  id: string;
  project_id: string;
  url: string;
  hostname: string;
  is_primary: boolean;
  verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface Competitor {
  id: string;
  project_id: string;
  name: string;
  website_url: string;
  hostname: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  industry: string | null;
  country: string | null;
  status: ProjectStatus;
  primary_domain: Domain | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
}

export interface ProjectCreateRequest {
  name: string;
  website_url: string;
  /** Required only when the user belongs to more than one organization. */
  organization_id?: string;
  description?: string;
  industry?: string;
  country?: string;
}

export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  industry?: string;
  country?: string;
  status?: ProjectStatus;
}

export interface DomainCreateRequest {
  url: string;
  is_primary?: boolean;
}

export interface CompetitorCreateRequest {
  name: string;
  website_url: string;
}

export interface StatusResponse {
  status: string;
}
