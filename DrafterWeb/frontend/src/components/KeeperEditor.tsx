import { useEffect, useRef, useState } from "react";
import type { KeeperDraft, Player } from "../types";
import { PositionBadge } from "./PositionBadge";

interface Props {
  teams: number;
  rounds: number;
  keepers: KeeperDraft[];
  onChange: (keepers: KeeperDraft[]) => void;
}

/**
 * Optional throughout. An empty list is a plain snake draft, so this stays
 * collapsed until asked for and never blocks starting a draft.
 */
export function KeeperEditor({ teams, rounds, keepers, onChange }: Props) {
  const [open, setOpen] = useState(false);

  // Shrinking the league can strand keepers on slots that no longer exist.
  useEffect(() => {
    const valid = keepers.filter((k) => k.team_slot <= teams && k.round <= rounds);
    if (valid.length !== keepers.length) onChange(valid);
  }, [teams, rounds, keepers, onChange]);

  function add() {
    onChange([...keepers, { team_slot: 1, round: 1, player_name: "" }]);
    setOpen(true);
  }

  function update(index: number, patch: Partial<KeeperDraft>) {
    onChange(keepers.map((k, i) => (i === index ? { ...k, ...patch } : k)));
  }

  function remove(index: number) {
    onChange(keepers.filter((_, i) => i !== index));
  }

  const taken = new Set(
    keepers.map((k) => `${k.team_slot}-${k.round}`),
  );
  const clash = keepers.length !== taken.size;

  return (
    <section className="rounded-lg border border-rule bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
            Keepers <span className="normal-case tracking-normal">(optional)</span>
          </h2>
          <p className="mt-1 text-sm text-ink-3">
            {keepers.length === 0
              ? "None set — this will be a plain snake draft."
              : `${keepers.length} keeper${keepers.length === 1 ? "" : "s"} across ${
                  new Set(keepers.map((k) => k.team_slot)).size
                } team${new Set(keepers.map((k) => k.team_slot)).size === 1 ? "" : "s"}.`}
          </p>
        </div>
        <div className="flex gap-2">
          {keepers.length > 0 && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
            >
              {open ? "Hide" : "Edit"}
            </button>
          )}
          <button
            type="button"
            onClick={add}
            className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
          >
            Add keeper
          </button>
        </div>
      </div>

      {open && keepers.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {keepers.map((keeper, i) => (
            <KeeperRow
              key={i}
              keeper={keeper}
              teams={teams}
              rounds={rounds}
              onChange={(patch) => update(i, patch)}
              onRemove={() => remove(i)}
            />
          ))}

          {clash && (
            <p className="text-sm text-danger">
              Two keepers share a team and round. Each roster spot holds one player.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function KeeperRow({
  keeper,
  teams,
  rounds,
  onChange,
  onRemove,
}: {
  keeper: KeeperDraft;
  teams: number;
  rounds: number;
  onChange: (patch: Partial<KeeperDraft>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-rule bg-ground p-2">
      <label className="flex items-center gap-1.5 text-xs text-ink-3">
        Team
        <select
          value={keeper.team_slot}
          onChange={(e) => onChange({ team_slot: Number(e.target.value) })}
          className="select-field rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
        >
          {Array.from({ length: teams }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-xs text-ink-3">
        Round
        <select
          value={keeper.round}
          onChange={(e) => onChange({ round: Number(e.target.value) })}
          className="select-field rounded border border-rule bg-surface px-2 py-1 text-sm text-ink"
        >
          {Array.from({ length: rounds }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      <PlayerPicker
        value={keeper.player_name}
        onChange={(player_name) => onChange({ player_name })}
      />

      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove keeper"
        className="ml-auto rounded px-2 py-1 text-xs text-ink-3 hover:text-danger"
      >
        Remove
      </button>
    </div>
  );
}

/**
 * Typeahead against the full player pool.
 *
 * Names must match the rankings exactly, and the two sources disagree about
 * suffixes, so picking from a list beats typing and hoping.
 */
function PlayerPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (name: string) => void;
}) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<Player[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => setQuery(value), [value]);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      fetch(`/api/players?search=${encodeURIComponent(query)}&limit=8`)
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled) setResults(d.players ?? []);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, open]);

  useEffect(() => {
    function away(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const unconfirmed = value.length > 0 && query !== value;

  return (
    <div ref={box} className="relative min-w-52 flex-1">
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Search for a player…"
        className={`w-full rounded border bg-surface px-2 py-1 text-sm ${
          unconfirmed ? "border-warn" : "border-rule"
        }`}
      />

      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-rule bg-surface shadow-lg">
          {results.map((p) => (
            <li key={p.key}>
              <button
                type="button"
                onMouseDown={() => {
                  onChange(p.name);
                  setQuery(p.name);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-raised"
              >
                <PositionBadge position={p.position} />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="tnum text-xs text-ink-3">{p.team}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
