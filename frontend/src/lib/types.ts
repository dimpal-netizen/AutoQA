/** Types mirroring the backend Pydantic schemas.
 *  From Phase 3 these can be generated from the OpenAPI schema instead. */

export type UserRole = "manual_qa" | "qa_engineer" | "test_manager" | "admin";

export type Browser = "chromium" | "firefox" | "webkit";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface Project {
  id: number;
  name: string;
  base_url: string;
  description: string | null;
  default_browsers: Browser[];
  settings: Record<string, unknown>;
  owner_id: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  base_url: string;
  description?: string | null;
  default_browsers?: Browser[];
}

/** Roles are hierarchical — test_manager can do anything qa_engineer can.
 *  Mirrors ROLE_LEVEL in backend/app/models/enums.py. */
export const ROLE_LEVEL: Record<UserRole, number> = {
  manual_qa: 1,
  qa_engineer: 2,
  test_manager: 3,
  admin: 4,
};

export const ROLE_LABEL: Record<UserRole, string> = {
  manual_qa: "Manual QA Engineer",
  qa_engineer: "QA Engineer",
  test_manager: "Test Manager",
  admin: "Admin",
};

export function hasRole(user: User | null, minimum: UserRole): boolean {
  if (!user) return false;
  return ROLE_LEVEL[user.role] >= ROLE_LEVEL[minimum];
}
