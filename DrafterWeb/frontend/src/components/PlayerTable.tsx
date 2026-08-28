import type { Player, Position } from "../types";
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
}: Props) {
  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-rule bg-surface">
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
              className="flex items-center gap-3 px-3 py-2 hover:bg-raised"
            >
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
                onClick={() => onDraft(player)}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-ground disabled:cursor-not-allowed disabled:opacity-35"
              >
                Draft
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
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
