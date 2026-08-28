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

export interface DraftSession {
  id: string;
  name: string;
  mode: string;
  seed: number;
  pick_seconds: number;
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

export interface KeeperDraft {
  team_slot: number;
  round: number;
  player_name: string;
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
