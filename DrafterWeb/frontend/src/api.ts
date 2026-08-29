import type {
  Advice,
  ConnectDraft,
  ContractBook,
  ContractMarket,
  ContractQuote,
  ContractSlate,
  KeeperImportResult,
  KeeperManager,
  KeeperOption,
  KeeperState,
  DraftSession,
  LiveDraft,
  NewSession,
  Player,
  PlayerProfile,
  Profile,
  SessionPatch,
  SessionSummary,
  Standing,
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
    // Never empty. `statusText` is always "" over HTTP/2 -- which this site is,
    // behind the tunnel -- and an ApiError carrying an empty string renders as
    // nothing, leaving a screen on "Loading…" forever instead of saying what
    // went wrong.
    let detail = "";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail)) {
        // FastAPI answers a bad parameter with a list of them.
        detail = body.detail
          .map((d: { msg?: string }) => d?.msg)
          .filter(Boolean)
          .join("; ");
      }
    } catch {
      // Not JSON. The status will have to do.
    }
    throw new ApiError(detail || response.statusText || `Request failed (${response.status})`,
                       response.status);
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

/** Contracts. A fourth tool, so a fourth client. */
export const contracts = {
  overview: () =>
    request<{
      you: KeeperManager | null;
      cap: number;
      start: number;
      ante: number;
      /** False until the commissioner marks your ante paid. */
      entered: boolean;
      balance: number | null;
      slates: ContractSlate[];
    }>("/api/contracts"),

  leaderboard: () =>
    request<{
      start: number;
      ante: number;
      waiting: string[];
      you: string | null;
      standings: Standing[];
    }>("/api/contracts/leaderboard"),

  slate: (id: string) =>
    request<{
      slate: ContractSlate;
      you: KeeperManager | null;
      markets: ContractMarket[];
    }>(`/api/contracts/slates/${id}`),

  /** Indicative: the trade route prices again against the committed book. */
  quote: (market_id: string, side: "yes" | "no", shares: number) =>
    request<ContractQuote>("/api/contracts/quote", {
      method: "POST",
      body: JSON.stringify({ market_id, side, shares }),
    }),

  trade: (market_id: string, side: "yes" | "no", shares: number) =>
    request<{
      traded: ContractQuote;
      market: ContractMarket;
      balance: number | null;
    }>("/api/contracts/trade", {
      method: "POST",
      body: JSON.stringify({ market_id, side, shares }),
    }),

  me: () => request<ContractBook>("/api/contracts/me"),
};

/** One player, from every angle the app has one. */
export const players = {
  profile: (ffcId: number, opts: { seasons?: number; atPick?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.seasons) q.set("seasons", String(opts.seasons));
    if (opts.atPick) q.set("at_pick", String(opts.atPick));
    const query = q.toString();
    return request<PlayerProfile>(
      `/api/players/${ffcId}/profile${query ? `?${query}` : ""}`,
    );
  },
};

/** Identity. Not the keeper tool's, though that is where the codes came from. */
export const me = {
  get: () => request<{ you: Profile | null }>("/api/me"),

  setPhoto: (photo: string) =>
    request<{ you: Profile }>("/api/me/photo", {
      method: "PUT",
      body: JSON.stringify({ photo }),
    }),

  clearPhoto: () => request<{ you: Profile }>("/api/me/photo", { method: "DELETE" }),
};
