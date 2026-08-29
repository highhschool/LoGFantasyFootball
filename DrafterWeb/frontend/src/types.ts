export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";

export interface Player {
  key: string;
  /** Fantasy Football Calculator's id, which the profile route is keyed on. */
  ffc_id: number;
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
  /** Zero for a player this year's rankings do not carry. */
  ffc_id: number;
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
  /** So a recommendation can be opened, not just read. */
  ffc_id: number;
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


/* ---------------------------------------------------------------- keepers */

export interface KeeperManager {
  user_id: string;
  display_name: string;
  team_name: string;
  claimed: boolean;
}

export interface KeeperOption {
  key: string;
  /** Zero for a player this year's board does not rank. */
  ffc_id: number;
  sleeper_id: string;
  name: string;
  position: string;
  team: string;
  bye_week: number | null;
  adp: number | null;
  /** The round keeping him costs, from where his ADP falls. */
  round: number;
  /** Close enough to a round boundary that the price could move. */
  near_boundary: boolean;
  /** Whether this year's ADP prices him at all. The unranked cost the last round. */
  ranked: boolean;
  keepable: boolean;
}

/** One league keeper, ready to drop into a mock draft's keeper list. */
export interface KeeperImport {
  team_slot: number;
  round: number;
  player_name: string;
  manager: string;
  position: string;
  adp: number | null;
}

export interface KeeperImportResult {
  /** True while selections can still change -- the caveat on an import. */
  open: boolean;
  /** Whose league it came from. A mock draft has none of its own. */
  league: string;
  managers: number;
  /** Managers who have not chosen yet. */
  waiting: string[];
  /** Managers Sleeper has given no draft slot, so they cannot be placed. */
  unordered: string[];
  keepers: KeeperImport[];
}

export interface KeeperState {
  open: boolean;
  deadline: string | null;
  you: KeeperManager | null;
  pick_key?: string | null;
  pick: {
    player_name: string;
    position: string;
    team: string;
    adp: number;
    round: number;
  } | null;
}

// ------------------------------------------------------------- contracts

export interface ContractSlate {
  slate_id: string;
  name: string;
  kind: "draft" | "weekly";
  /** Which money. Fixed for the slate's life. */
  stakes: "play" | "real";
  opens_at: string;
  closes_at: string | null;
  markets?: number;
  settled?: number;
}

export interface ContractPosition {
  yes: number;
  no: number;
  /** Net cents paid in; negative means taken out. */
  cash: number;
  /** What the holding would fetch at the current line. */
  value: number;
  open_pnl: number;
}

export interface ContractMarket {
  market_id: string;
  question: string;
  price_yes: number;
  price_no: number;
  traded: number;
  kind: string;
  slate_id: string;
  game: string | null;
  closes_at: string;
  phase: "pending" | "open" | "closed" | "settled";
  resolved: boolean | null;
  cap: number;
  stakes: "play" | "real";
  /** Zero unless the market is about a particular player. */
  ffc_id: number;
  /** Only present once you have signed in. */
  you?: ContractPosition;
  headroom?: number;
}

export interface Standing {
  rank: number;
  /** What they started with. Zero until their ante is paid. */
  start: number;
  /** Whether they have paid into the season pot. */
  entered: boolean;
  user_id: string;
  manager: string;
  /** Spendable. */
  balance: number;
  /** Balance plus what open positions would fetch. What the table ranks. */
  equity: number;
  staked: number;
  settled_pnl: number;
  open_pnl: number;
  profit: number;
  markets: number;
}

export interface ContractQuote {
  cash: number;
  shares: number;
  price_before: number;
  price_after: number;
  indicative?: boolean;
  legs: { side: string; shares: number; cash: number }[];
}

export interface ContractBookEntry {
  market_id: string;
  question: string;
  slate_id: string;
  yes: number;
  no: number;
  cash: number;
  value: number;
  open_pnl: number;
  price_yes: number;
  result?: number;
}

export interface ContractBook {
  you: KeeperManager;
  open: ContractBookEntry[];
  settled: ContractBookEntry[];
  realised: number;
  unrealised: number;
}

/** Who you are, and the picture to draw for you. */
export interface Profile {
  user_id: string;
  display_name: string;
  team_name: string;
  draft_slot: number | null;
  /** An uploaded data URL, or null. */
  photo: string | null;
  /** Sleeper's avatar, the free default. */
  avatar_url: string | null;
  custom: boolean;
}

// --------------------------------------------------------------- profiles

export interface PlayerProfile {
  player: {
    ffc_id: number;
    key: string;
    name: string;
    position: Position;
    team: string;
    team_full: string;
    bye_week: number | null;
    rookie: boolean;
    headshot: string | null;
  };
  adp: {
    adp: number;
    round: string;
    rank: number;
    pos_rank: number;
    high: number;
    low: number;
    stdev: number;
    times_drafted: number;
    /** Percent still available at `at_pick`, when one was asked for. */
    survives_to: number | null;
    at_pick: number | null;
  };
  bio: {
    age: number | null;
    college: string | null;
    years_exp: number | null;
    number: string | null;
    height: string | null;
    weight: string | null;
    depth_chart_order: number | null;
    injury_status: string | null;
    status: string | null;
  } | null;
  career: {
    columns: string[];
    seasons: Record<string, number | null>[];
  };
  notes: { title: string; body: string; updated: string; priority: number }[];
  /** Which halves came back. Each source can fail on its own. */
  have: { career: boolean; bio: boolean; notes: boolean };
  season: number;
}
