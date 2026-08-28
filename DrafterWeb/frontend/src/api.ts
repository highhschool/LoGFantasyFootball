import type { DraftSession, NewSession, Player, SessionSummary } from "./types";

/** Surfaces the server's own message rather than a generic failure string. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; the status text will have to do.
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

export interface Health {
  status: "ok" | "degraded";
  season: number;
  rankings: string;
  players_loaded: number;
  error: string | null;
}

export const api = {
  health: () => request<Health>("/api/health"),

  listSessions: () =>
    request<{ sessions: SessionSummary[] }>("/api/sessions").then((r) => r.sessions),

  createSession: (body: NewSession) =>
    request<DraftSession>("/api/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getSession: (id: string) => request<DraftSession>(`/api/sessions/${id}`),

  deleteSession: (id: string) =>
    request<{ deleted: string }>(`/api/sessions/${id}`, { method: "DELETE" }),

  available: (id: string, opts: { position?: string; search?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.position) params.set("position", opts.position);
    if (opts.search) params.set("search", opts.search);
    params.set("limit", String(opts.limit ?? 100));
    return request<{ count: number; players: Player[] }>(
      `/api/sessions/${id}/available?${params}`,
    ).then((r) => r.players);
  },

  pick: (id: string, playerKey: string) =>
    request<DraftSession>(`/api/sessions/${id}/pick`, {
      method: "POST",
      body: JSON.stringify({ player_key: playerKey }),
    }),

  undo: (id: string) =>
    request<DraftSession>(`/api/sessions/${id}/undo`, { method: "POST" }),

  autopick: (id: string) =>
    request<DraftSession>(`/api/sessions/${id}/autopick`, { method: "POST" }),

  simulate: (id: string) =>
    request<DraftSession>(`/api/sessions/${id}/simulate`, { method: "POST" }),
};
