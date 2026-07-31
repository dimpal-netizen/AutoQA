/** Thin fetch wrapper around the AutoQA backend.
 *
 *  Reads the access token from the auth store, and on a 401 tries the refresh
 *  token exactly once before giving up and logging the user out.
 */

import { useAuthStore } from "@/stores/auth-store";
import type {
  Project,
  ProjectCreate,
  RecordingSession,
  RecordingSessionDetail,
  TokenPair,
  User,
} from "@/lib/types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn a FastAPI error body into a readable message.
 *  Service errors give {detail: "..."}; 422 gives {detail: [{loc, msg}, ...]}. */
async function messageFrom(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      return detail
        .map((e) => {
          const field = Array.isArray(e.loc) ? e.loc.at(-1) : undefined;
          return field ? `${field}: ${e.msg}` : e.msg;
        })
        .join(", ");
    }
  } catch {
    // Body was not JSON — fall through to the status text.
  }
  return response.statusText || `Request failed (${response.status})`;
}

async function rawRequest<T>(
  path: string,
  options: RequestInit,
  token: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    throw new ApiError(await messageFrom(response), response.status);
  }

  // 204 No Content has no body to parse.
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const store = useAuthStore.getState();

  try {
    return await rawRequest<T>(path, options, store.accessToken);
  } catch (error) {
    const isExpired = error instanceof ApiError && error.status === 401;
    if (!isExpired || !store.refreshToken) throw error;

    // Access token expired — swap it for a fresh one and retry once.
    try {
      const tokens = await rawRequest<TokenPair>(
        "/auth/refresh",
        {
          method: "POST",
          body: JSON.stringify({ refresh_token: store.refreshToken }),
        },
        null,
      );
      store.setSession(tokens);
      return await rawRequest<T>(path, options, tokens.access_token);
    } catch {
      // The refresh token is dead too — the session is genuinely over.
      store.logout();
      throw error;
    }
  }
}

export const api = {
  auth: {
    register: (data: {
      email: string;
      password: string;
      full_name?: string;
      role?: string;
    }) =>
      request<TokenPair>("/auth/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    login: (email: string, password: string) =>
      request<TokenPair>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),

    me: () => request<User>("/auth/me"),
  },

  projects: {
    list: () => request<Project[]>("/projects"),

    get: (id: number) => request<Project>(`/projects/${id}`),

    create: (data: ProjectCreate) =>
      request<Project>("/projects", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    update: (id: number, data: Partial<ProjectCreate>) =>
      request<Project>(`/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),

    remove: (id: number) =>
      request<void>(`/projects/${id}`, { method: "DELETE" }),
  },

  recordings: {
    list: (projectId?: number) =>
      request<RecordingSession[]>(
        projectId ? `/recordings?project_id=${projectId}` : "/recordings",
      ),

    get: (id: number) => request<RecordingSessionDetail>(`/recordings/${id}`),

    /** Opens `url` in a real browser with the recorder injected. */
    launch: (projectId: number, data: { url: string; name?: string }) =>
      request<RecordingSession>(`/projects/${projectId}/recordings/launch`, {
        method: "POST",
        body: JSON.stringify(data),
      }),

    /** Closes a launched browser and finalises the recording. */
    close: (id: number) =>
      request<RecordingSession>(`/recordings/${id}/close`, { method: "POST" }),

    remove: (id: number) =>
      request<void>(`/recordings/${id}`, { method: "DELETE" }),
  },
};
