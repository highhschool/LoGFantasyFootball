import { useEffect, useRef, useState } from "react";
import { ApiError, keeper as keeperApi } from "../api";
import type { KeeperDraft, Player, Profile } from "../types";
import { PositionBadge } from "./PositionBadge";
import { SignIn } from "./SignIn";

interface Props {
  teams: number;
  rounds: number;
  keepers: KeeperDraft[];
  /** A mock draft has no league of its own; it gets one from the account. */
  profile: Profile | null;
  onChange: (keepers: KeeperDraft[]) => void;
  onSignedIn: () => void;
}

/**
 * Optional throughout. An empty list is a plain snake draft, so this stays
 * collapsed until asked for and never blocks starting a draft.
 */
export function KeeperEditor({ teams, rounds, keepers, profile, onChange, onSignedIn }: Props) {
  const [open, setOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [askSignIn, setAskSignIn] = useState(false);

  /**
   * Pull the league's real keepers in, slot and round together.
   *
   * The keeper tool knows the round from ADP and Sleeper knows the slot from
   * the draft order; neither alone can place a player on a board. Replaces
   * rather than appends -- importing twice should leave twelve keepers, not
   * twenty-four.
   *
   * Available before the lock, because the point is to mock against the real
   * keepers while there is still time for it to matter. They are provisional
   * until then, which the note says.
   *
   * Needs an account. The mock draft does not know about any league; it asks
   * whoever is running it, and the answer arrives with their sign-in.
   */
  async function importLeague() {
    if (!profile) {
      setAskSignIn(true);
      return;
    }
    setImporting(true);
    setNote(null);
    setProblem(null);
    try {
      const data = await keeperApi.forImport();

      const fits = data.keepers.filter(
        (k) => k.team_slot <= teams && k.round <= rounds,
      );
      onChange(
        fits.map((k) => ({
          team_slot: k.team_slot,
          round: k.round,
          player_name: k.player_name,
        })),
      );

      const asides = [
        data.waiting.length && `${data.waiting.join(", ")} have not chosen`,
        data.unordered.length && `no draft slot for ${data.unordered.join(", ")}`,
        fits.length < data.keepers.length &&
          `${data.keepers.length - fits.length} outside a ${teams}-team, ${rounds}-round draft`,
      ].filter(Boolean);

      setAskSignIn(false);
      setNote(
        `Imported ${fits.length} of ${data.managers} in ${data.league}'s league` +
          (asides.length ? ` — ${asides.join("; ")}.` : ".") +
          // Worth saying every time: a mock run today can be built on a
          // keeper somebody swaps out on Sunday afternoon.
          (data.open ? " Keepers can still change until the lock." : ""),
      );
      if (fits.length) setOpen(true);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : String(e));
    } finally {
      setImporting(false);
    }
  }

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
            onClick={importLeague}
            disabled={importing}
            title="Pull every manager's keeper from the league, with the round their ADP costs"
            className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
          >
            {importing ? "Importing…" : "Import league"}
          </button>
          <button
            type="button"
            onClick={add}
            className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
          >
            Add keeper
          </button>
        </div>
      </div>

      {askSignIn && !profile && (
        <div className="mt-4 rounded-md border border-rule bg-ground p-4">
          <SignIn
            heading="Sign in to import your league"
            blurb="Keepers come from your league, so the app needs to know whose you are."
            onSignedIn={() => {
              setAskSignIn(false);
              onSignedIn();
            }}
          />
        </div>
      )}

      {note && <p className="mt-3 text-sm text-ink-2">{note}</p>}
      {problem && <p className="mt-3 text-sm text-danger">{problem}</p>}

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
 * What you type is the value. An earlier version only reported a name when a
 * suggestion was clicked, so typing one and pressing start silently dropped the
 * keeper -- the field looked filled in and the draft ran without it. The list
 * is a convenience for getting the spelling right, not the only way to answer.
 */
function PlayerPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (name: string) => void;
}) {
  const [results, setResults] = useState<Player[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || value.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      fetch(`/api/players?search=${encodeURIComponent(value)}&limit=8`)
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
  }, [value, open]);

  useEffect(() => {
    function away(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const empty = value.trim() === "";

  return (
    <div ref={box} className="relative min-w-52 flex-1">
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Search for a player…"
        aria-invalid={empty}
        className={`w-full rounded border bg-surface px-2 py-1 text-sm ${
          empty ? "border-warn" : "border-rule"
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
