import { useState } from "react";
import { api } from "../api";
import type { AdpProvenance } from "../api";
import type { KeeperDraft, NewSession, SessionSummary } from "../types";
import { AdpBadge } from "./AdpBadge";
import { InlineName } from "./InlineName";
import { KeeperEditor } from "./KeeperEditor";
import { SlotPicker } from "./SlotPicker";

// The league drafts 15 rounds, and the default position limits hold
// exactly 15 players, so this is a roster constraint rather than a
// preference. The API rejects anything above it.
const MAX_ROUNDS = 15;
const TEAM_OPTIONS = [8, 10, 12];

interface Props {
  sessions: SessionSummary[];
  starting: boolean;
  error: string | null;
  adp?: AdpProvenance;
  onStart: (body: NewSession) => void;
  onResume: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onBack: () => void;
}

export function Setup({
  sessions,
  starting,
  error,
  adp,
  onStart,
  onResume,
  onRename,
  onDelete,
  onBack,
}: Props) {
  const [teams, setTeams] = useState(12);
  const [rounds, setRounds] = useState(15);
  const [slot, setSlot] = useState(6);
  const [randomness, setRandomness] = useState(1);
  const [pickSeconds, setPickSeconds] = useState(0);
  const [name, setName] = useState("");
  const [keepers, setKeepers] = useState<KeeperDraft[]>([]);

  // A keeper row with no player used to be filtered out at submit, so the
  // draft ran without it and nothing said why. Block instead.
  const blankKeepers = keepers.filter((k) => k.player_name.trim() === "").length;
  const [copied, setCopied] = useState<string | null>(null);

  /** Reuse a previous draft's setup: league shape, clock, variance, keepers. */
  async function copySettings(id: string, label: string) {
    try {
      const previous = await api.getSession(id);
      const c = previous.config;

      setTeams(TEAM_OPTIONS.includes(c.teams) ? c.teams : 12);
      setRounds(Math.min(c.rounds, MAX_ROUNDS));
      setSlot(Math.min(c.your_slot, c.teams));
      setRandomness(previous.randomness);
      setPickSeconds(previous.pick_seconds);
      setKeepers(c.keepers.map((k) => ({ ...k })));
      setName(previous.name);
      setCopied(label);
    } catch {
      setCopied(null);
    }
  }
  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-6 overflow-y-auto p-6">
      <header className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onBack}
          className="self-start text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Tools
        </button>
        <h1 className="text-3xl font-semibold tracking-tight">Mock draft</h1>
        <AdpBadge adp={adp} className="mt-2" />
      </header>

      <section className="rounded-lg border border-rule bg-surface p-5">
        <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
          New mock draft
        </h2>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Teams">
            <select
              value={teams}
              onChange={(e) => {
                const next = Number(e.target.value);
                setTeams(next);
                if (slot > next) setSlot(next);
              }}
              className="select-field w-full rounded-md border border-rule bg-ground px-3 py-2"
            >
              {TEAM_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Rounds">
            <select
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
              className="select-field w-full rounded-md border border-rule bg-ground px-3 py-2"
            >
              {Array.from({ length: MAX_ROUNDS }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Session name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`Slot ${slot} mock`}
              maxLength={80}
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
            />
          </Field>

          <Field label="On the clock">
            <select
              value={pickSeconds}
              onChange={(e) => setPickSeconds(Number(e.target.value))}
              className="select-field w-full rounded-md border border-rule bg-ground px-3 py-2"
            >
              <option value={0}>No timer</option>
              <option value={30}>30 seconds</option>
              <option value={60}>1 minute</option>
              <option value={90}>90 seconds</option>
              <option value={120}>2 minutes</option>
              <option value={300}>5 minutes</option>
            </select>
          </Field>

          <Field label={randomnessLabel(randomness)}>
            <input
              type="range"
              min={0}
              max={2}
              step={0.25}
              value={randomness}
              onChange={(e) => setRandomness(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </Field>
        </div>

        <div className="mt-4">
          <SlotPicker teams={teams} slot={slot} onChange={setSlot} />
        </div>

        {pickSeconds > 0 && (
          <p className="mt-3 text-sm text-ink-3">
            When the clock runs out your pick is made for you, the same as a real
            draft. It only runs on your turn.
          </p>
        )}

        <p className="mt-3 text-sm text-ink-3">
          Bots draft by ADP, jittered by each player's real draft-to-draft spread,
          so no two mocks come out the same. Set it to zero for a strict
          chalk board.
        </p>

        {copied && (
          <p className="mt-3 text-sm text-accent">
            Settings copied from “{copied}”. Adjust anything below, then start.
          </p>
        )}

        {blankKeepers > 0 && (
          <p className="mt-3 text-sm text-warn">
            {blankKeepers === 1
              ? "One keeper has no player set."
              : `${blankKeepers} keepers have no player set.`}{" "}
            Name them or remove the rows before starting.
          </p>
        )}

        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        <button
          type="button"
          disabled={starting || blankKeepers > 0}
          onClick={() =>
            onStart({
              name: name.trim() || `Slot ${slot} mock`,
              teams,
              rounds,
              your_slot: slot,
              randomness,
              pick_seconds: pickSeconds,
              keepers,
            })
          }
          className="mt-4 rounded-md bg-accent px-4 py-2 font-semibold text-ground disabled:opacity-50"
        >
          {starting ? "Starting…" : "Start draft"}
        </button>
      </section>

      <KeeperEditor
        teams={teams}
        rounds={rounds}
        keepers={keepers}
        onChange={setKeepers}
      />

      {sessions.length > 0 && (
        <section className="rounded-lg border border-rule bg-surface">
          <h2 className="border-b border-rule px-4 py-2.5 text-sm font-semibold tracking-wider text-ink-3 uppercase">
            Resume
          </h2>
          <ul className="divide-y divide-rule">
            {sessions.map((s) => (
              <li key={s.id} className="flex items-center gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <InlineName
                    value={s.name || s.id}
                    onRename={(name) => onRename(s.id, name)}
                    activateOn="dblclick"
                    className="-ml-1 block max-w-full text-sm font-medium"
                    inputClassName="w-full text-sm font-medium"
                  />
                  <div className="text-xs text-ink-3">
                    {s.picks_made} picks · {new Date(s.updated_at).toLocaleString()}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => copySettings(s.id, s.name || s.id)}
                  title="Load this draft's settings into the form above"
                  className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
                >
                  Copy settings
                </button>
                <button
                  type="button"
                  onClick={() => onResume(s.id)}
                  className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(s.id)}
                  className="rounded-md px-2 py-1.5 text-xs text-ink-3 hover:text-danger"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function randomnessLabel(value: number): string {
  if (value === 0) return "Bot variance — none (pure ADP)";
  if (value <= 0.5) return "Bot variance — low";
  if (value <= 1) return "Bot variance — realistic";
  if (value <= 1.5) return "Bot variance — high";
  return "Bot variance — chaotic";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}
