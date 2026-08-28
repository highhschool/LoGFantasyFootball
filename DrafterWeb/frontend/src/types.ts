export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";

export interface Player {
  key: string;
  name: string;
  position: Position;
  team: string;
  bye_week: number | null;
  adp: number;
  pos_rank: number;
  stdev: number;
}

export interface Pick {
  overall: number;
  round: number;
  team_slot: number;
  player_name: string;
  position: Position;
  team: string;
  bye_week: number | null;
  adp: number;
  source: "user" | "bot" | "keeper" | "sleeper" | "manual" | "remote";
}

export interface RosterSpot {
  player_name: string;
  position: Position;
  team: string;
  bye_week: number | null;
  round: number;
  adp: number;
}

export interface OnTheClock {
  overall: number;
  round: number;
  pick_in_round: number;
  team_slot: number;
}

export interface KeeperDraft {
  team_slot: number;
  round: number;
  player_name: string;
}

export interface DraftSession {
  id: string;
  name: string;
  mode: string;
  seed: number;
  pick_seconds: number;
  randomness: number;
  config: {
    teams: number;
    rounds: number;
    your_slot: number;
    position_limits: Record<string, number>;
    keepers: KeeperDraft[];
  };
  complete: boolean;
  your_turn: boolean;
  on_the_clock: OnTheClock | null;
  picks_until_your_next: number | null;
  picks: Pick[];
  your_roster: RosterSpot[];
  your_needs: Record<string, number>;
  bye_clashes: Record<string, number>;
  unresolved_keepers: string[];
}

export interface SessionSummary {
  id: string;
  name: string;
  mode: string;
  created_at: string;
  updated_at: string;
  picks_made: number;
}

export interface NewSession {
  name: string;
  teams: number;
  rounds: number;
  your_slot: number;
  randomness: number;
  pick_seconds: number;
  keepers: KeeperDraft[];
  seed?: number;
}

export interface SessionPatch {
  name?: string;
  pick_seconds?: number;
}


/* ---------------------------------------------------------------- shared

   The board and roster panels are used by both tools, so they depend on the
   shape they actually read rather than on either tool's whole session. Both
   session types satisfy these structurally. */

export interface BoardView {
  config: { teams: number; rounds: number; your_slot: number };
  picks: Pick[];
  on_the_clock: OnTheClock | null;
}

export interface RosterView {
  config: { rounds: number };
  your_roster: RosterSpot[];
  your_needs: Record<string, number>;
  bye_clashes: Record<string, number>;
  unresolved_keepers?: string[];
}

export interface Advice {
  key: string;
  name: string;
  position: Position;
  team: string;
  bye_week: number | null;
  adp: number;
  score: number;
  /** Chance he is still available at your next pick. */
  survival: number;
  /** Picks he has fallen past his ADP; negative is a reach. */
  value: number;
  need: number;
  /** Where he would go in your lineup. */
  slot: "starter" | "flex" | "bench";
  starters_left: number;
  bye_clash: boolean;
  gone_by_next: boolean;
  /** ADP picks lost by waiting a turn at this position. */
  dropoff: number;
  /** Who you would likely be choosing from instead. */
  alternative: string;
  alternative_adp: number;
  tier_remaining: number;
  reasons: string[];
}

/* ------------------------------------------------------- live assistant */

export interface UnrankedPick {
  pick_no: number;
  round: number;
  team_slot: number;
  name: string;
  position: Position;
  team: string;
}

export interface LiveDraft {
  id: string;
  name: string;
  mode: "assistant";
  your_slot: number;
  config: {
    teams: number;
    rounds: number;
    your_slot: number;
    position_limits: Record<string, number>;
  };
  complete: boolean;
  your_turn: boolean;
  on_the_clock: OnTheClock | null;
  picks_until_your_next: number | null;
  picks: Pick[];
  your_roster: RosterSpot[];
  your_needs: Record<string, number>;
  bye_clashes: Record<string, number>;
  unranked: UnrankedPick[];
  /** Set when Sleeper could not be reached; the board shown is what we had. */
  sync_error?: string;
}

export interface ConnectDraft {
  draft: string;
  your_slot: number;
  name?: string;
}
