import type {
  Advice,
  ConnectDraft,
  KeeperImportResult,
  KeeperManager,
  KeeperOption,
  KeeperState,
  DraftSession,
  LiveDraft,
  NewSession,
  Player,
  SessionPatch,
  SessionSummary,
} from "./types";

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

export interface AdpProvenance {
  source: "api" | "cache" | "csv";
  year: number;
  scoring: string | null;
  teams: number | null;
  fetched_at: string | null;
  age_seconds: number | null;
  total_drafts: number | null;
  sampled_from: string | null;
  sampled_to: string | null;
  stale: boolean;
  age: string;
}

export interface Health {
  status: "ok" | "degraded";
  season: number;
  players_loaded: number;
  error: string | null;
  adp?: AdpProvenance;
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

  updateSession: (id: string, patch: SessionPatch) =>
    request<DraftSession>(`/api/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteSession: (id: string) =>
    request<{ deleted: string }>(`/api/sessions/${id}`, { method: "DELETE" }),

  available: (id: string, opts: { position?: string; search?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.position) params.set("position", opts.position);
    if (opts.search) params.set("search", opts.search);
    params.set("limit", String(opts.limit ?? 1000));
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

  advice: (id: string, limit = 5) =>
    request<{ advice: Advice[] }>(`/api/sessions/${id}/advice?limit=${limit}`).then(
      (r) => r.advice,
    ),
};

/** The live assistant. A separate tool, so a separate client. */
export const live = {
  list: () =>
    request<{ sessions: SessionSummary[] }>("/api/assistant").then((r) => r.sessions),

  connect: (body: ConnectDraft) =>
    request<LiveDraft>("/api/assistant", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  get: (id: string) => request<LiveDraft>(`/api/assistant/${id}`),

  sync: (id: string) =>
    request<LiveDraft>(`/api/assistant/${id}/sync`, { method: "POST" }),

  remove: (id: string) =>
    request<{ deleted: string }>(`/api/assistant/${id}`, { method: "DELETE" }),

  advice: (id: string, limit = 5) =>
    request<{ advice: Advice[] }>(`/api/assistant/${id}/advice?limit=${limit}`).then(
      (r) => r.advice,
    ),
};

/** Keeper selection. A third tool, so a third client. */
export const keeper = {
  status: () => request<KeeperState>("/api/keeper"),

  managers: () =>
    request<{ managers: KeeperManager[] }>("/api/keeper/managers").then((r) => r.managers),

  claim: (user_id: string, code: string) =>
    request<{ you: KeeperManager }>("/api/keeper/claim", {
      method: "POST",
      body: JSON.stringify({ user_id, code }),
    }),

  roster: () =>
    request<{
      selected: string | null;
      season: number;
      rounds: number;
      options: KeeperOption[];
    }>("/api/keeper/roster"),

  pick: (player_key: string) =>
    request<unknown>("/api/keeper/pick", {
      method: "POST",
      body: JSON.stringify({ player_key }),
    }),

  clear: () => request<unknown>("/api/keeper/pick", { method: "DELETE" }),

  /** The league's keepers as slot/round pairs, for a mock draft. */
  forImport: () => request<KeeperImportResult>("/api/keeper/import"),
};
