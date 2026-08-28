import { useState } from "react";
import type { AdpProvenance } from "../api";
import type { KeeperDraft, NewSession, SessionSummary } from "../types";
import { AdpBadge } from "./AdpBadge";
import { KeeperEditor } from "./KeeperEditor";
import { SlotPicker } from "./SlotPicker";

// The league drafts 15 rounds, and the default position limits hold
// exactly 15 players, so this is a roster constraint rather than a
// preference. The API rejects anything above it.
const MAX_ROUNDS = 15;

interface Props {
  sessions: SessionSummary[];
  starting: boolean;
  error: string | null;
  adp?: AdpProvenance;
  onStart: (body: NewSession) => void;
  onResume: (id: string) => void;
  onDelete: (id: string) => void;
}

export function Setup({
  sessions,
  starting,
  error,
  adp,
  onStart,
  onResume,
  onDelete,
}: Props) {
  const [teams, setTeams] = useState(12);
  const [rounds, setRounds] = useState(15);
  const [slot, setSlot] = useState(6);
  const [randomness, setRandomness] = useState(1);
  const [pickSeconds, setPickSeconds] = useState(0);
  const [name, setName] = useState("");
  const [keepers, setKeepers] = useState<KeeperDraft[]>([]);
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">NGFL Drafter</h1>
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
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
            >
              {[8, 10, 12].map((n) => (
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
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
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
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
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

        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        <button
          type="button"
          disabled={starting}
          onClick={() =>
            onStart({
              name: name.trim() || `Slot ${slot} mock`,
              teams,
              rounds,
              your_slot: slot,
              randomness,
              pick_seconds: pickSeconds,
              keepers: keepers.filter((k) => k.player_name.trim() !== ""),
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
                  <div className="truncate text-sm font-medium">{s.name || s.id}</div>
                  <div className="text-xs text-ink-3">
                    {s.picks_made} picks · {new Date(s.updated_at).toLocaleString()}
                  </div>
                </div>
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
