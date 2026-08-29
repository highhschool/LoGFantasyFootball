import { useState } from "react";
import type { Player, Position } from "../types";
import { PlayerProfile } from "./PlayerProfile";
import { PositionBadge } from "./PositionBadge";

const POSITIONS: Position[] = ["QB", "RB", "WR", "TE", "K", "DST"];

interface Props {
  players: Player[];
  loading: boolean;
  disabled: boolean;
  search: string;
  position: string;
  onSearch: (value: string) => void;
  onPosition: (value: string) => void;
  onDraft: (player: Player) => void;
  /** Keys of the players being compared, at most two and all one position. */
  compare: string[];
  /** The position a comparison is locked to, once one is under way. */
  comparePosition: Position | null;
  onCompare: (player: Player) => void;
  /** Your next pick, so a profile can say whether he lasts to it. */
  atPick?: number;
  className?: string;
  style?: React.CSSProperties;
}

export function PlayerTable({
  players,
  loading,
  disabled,
  search,
  position,
  onSearch,
  onPosition,
  onDraft,
  compare,
  comparePosition,
  onCompare,
  atPick,
  className = "",
  style,
}: Props) {
  const [profile, setProfile] = useState<number | null>(null);

  return (
    <section
      style={style}
      className={`flex min-h-0 flex-col rounded-lg border border-rule bg-surface ${className}`}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-rule p-3">
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search players…"
          className="min-w-40 flex-1 rounded-md border border-rule bg-ground px-3 py-1.5 text-sm placeholder:text-ink-3"
        />
        <div className="flex flex-wrap gap-1">
          <FilterChip label="All" active={position === ""} onClick={() => onPosition("")} />
          {POSITIONS.map((p) => (
            <FilterChip
              key={p}
              label={p}
              active={position === p}
              onClick={() => onPosition(position === p ? "" : p)}
            />
          ))}
        </div>
      </header>

      {/* Naming the column, since a bare checkbox beside a player is as
          likely to read as "shortlist" or "hide" as it is "compare". */}
      <p className="border-b border-rule px-3 py-1 text-[10px] font-semibold tracking-wider text-ink-3 uppercase">
        Compare
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="p-4 text-sm text-ink-3">Loading…</p>}

        {!loading && players.length === 0 && (
          <p className="p-4 text-sm text-ink-3">
            No available players match that filter.
          </p>
        )}

        <ul className="divide-y divide-rule">
          {players.map((player) => (
            <li
              key={player.key}
              role={player.ffc_id ? "button" : undefined}
              tabIndex={player.ffc_id ? 0 : undefined}
              onClick={player.ffc_id ? () => setProfile(player.ffc_id) : undefined}
              onKeyDown={(e) => {
                if (player.ffc_id && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  setProfile(player.ffc_id);
                }
              }}
              title={player.ffc_id ? "Career, ADP and the latest on him" : undefined}
              className={`flex items-center gap-3 px-3 py-2 hover:bg-raised focus-visible:bg-raised focus-visible:outline-none ${
                player.ffc_id ? "cursor-pointer" : ""
              }`}
            >
              <CompareBox
                player={player}
                checked={compare.includes(player.key)}
                full={compare.length >= 2}
                locked={comparePosition}
                onToggle={onCompare}
              />

              <PositionBadge position={player.position} />

              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{player.name}</div>
                <div className="text-xs text-ink-3">
                  {player.team}
                  {player.bye_week !== null && <> · bye {player.bye_week}</>}
                  {" · "}
                  {player.position}
                  {player.pos_rank}
                </div>
              </div>

              <div className="tnum text-right text-xs text-ink-2">
                <div className="font-semibold">{player.adp.toFixed(1)}</div>
                <div className="text-ink-3">±{player.stdev.toFixed(1)}</div>
              </div>

              <button
                type="button"
                disabled={disabled}
                onClick={(e) => {
                  e.stopPropagation();
                  onDraft(player);
                }}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-ground disabled:cursor-not-allowed disabled:opacity-35"
              >
                Draft
              </button>
            </li>
          ))}
        </ul>
      </div>

      {profile !== null && (
        <PlayerProfile
          ffcId={profile}
          atPick={atPick}
          onClose={() => setProfile(null)}
        />
      )}
    </section>
  );
}

/**
 * The tick that puts a player up against another.
 *
 * Disabled rather than hidden when it cannot be used, and each reason says
 * itself on hover: two is the most a table can be read across, the columns are
 * chosen by position so a pair has to share one, and a player the rankings do
 * not carry has no seasons to show.
 */
function CompareBox({
  player,
  checked,
  full,
  locked,
  onToggle,
}: {
  player: Player;
  checked: boolean;
  full: boolean;
  locked: Position | null;
  onToggle: (player: Player) => void;
}) {
  const wrongPosition = locked !== null && locked !== player.position;
  const noStats = !player.ffc_id;
  // Unticking has to stay available whatever else is true, or a full pair
  // would lock itself in.
  const disabled = !checked && (noStats || wrongPosition || full);

  const why = noStats
    ? "No season data for this player"
    : wrongPosition
      ? `Comparing ${locked}s — clear it to compare ${player.position}s`
      : full
        ? "Two at a time; untick one first"
        : checked
          ? `Stop comparing ${player.name}`
          : `Compare ${player.name}`;

  return (
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      // The row opens a profile; ticking a box in it should not.
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => {
        e.stopPropagation();
        onToggle(player);
      }}
      aria-label={why}
      title={why}
      className="size-4 shrink-0 accent-accent disabled:opacity-25"
    />
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-2 py-1 text-xs font-medium ${
        active ? "bg-accent text-ground" : "bg-raised text-ink-2 hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}
