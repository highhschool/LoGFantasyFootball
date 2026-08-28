import { useState } from "react";
import type { AdpProvenance } from "../api";
import type { ConnectDraft, SessionSummary } from "../types";
import { AdpBadge } from "./AdpBadge";
import { InlineName } from "./InlineName";
import { SlotPicker } from "./SlotPicker";

interface Props {
  drafts: SessionSummary[];
  connecting: boolean;
  error: string | null;
  adp?: AdpProvenance;
  onConnect: (body: ConnectDraft) => void;
  onOpen: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onBack: () => void;
}

// Only the slot is asked for. Everything else about the draft -- team count,
// rounds, who has picked -- is read from Sleeper, because Sleeper already
// knows and a mismatch would seat every pick wrongly.
const MAX_SLOTS = 12;

export function LiveSetup({
  drafts,
  connecting,
  error,
  adp,
  onConnect,
  onOpen,
  onRename,
  onDelete,
  onBack,
}: Props) {
  const [draft, setDraft] = useState("");
  const [slot, setSlot] = useState(1);
  const [name, setName] = useState("");

  const ready = draft.trim() !== "";

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onBack}
          className="self-start text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Tools
        </button>
        <h1 className="text-3xl font-semibold tracking-tight">Live draft assistant</h1>
        <AdpBadge adp={adp} />
      </header>

      <section className="rounded-lg border border-rule bg-surface p-5">
        <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
          Follow a Sleeper draft
        </h2>

        <div className="mt-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-ink-2">Draft link</span>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="https://sleeper.com/draft/nfl/…"
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
            />
            <span className="text-xs text-ink-3">
              Open your draft on Sleeper and paste the address. The draft id on
              its own works too.
            </span>
          </label>

          <SlotPicker teams={MAX_SLOTS} slot={slot} onChange={setSlot} />

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-ink-2">Name (optional)</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`Live draft · slot ${slot}`}
              maxLength={80}
              className="w-full rounded-md border border-rule bg-ground px-3 py-2"
            />
          </label>
        </div>

        <p className="mt-3 text-sm text-ink-3">
          Team count and rounds come from Sleeper, so there is nothing else to
          set. The board fills itself in as picks are made.
        </p>

        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        <button
          type="button"
          disabled={connecting || !ready}
          onClick={() => onConnect({ draft: draft.trim(), your_slot: slot, name: name.trim() })}
          className="mt-4 rounded-md bg-accent px-4 py-2 font-semibold text-ground disabled:opacity-50"
        >
          {connecting ? "Connecting…" : "Connect"}
        </button>
      </section>

      {drafts.length > 0 && (
        <section className="rounded-lg border border-rule bg-surface">
          <h2 className="border-b border-rule px-4 py-2.5 text-sm font-semibold tracking-wider text-ink-3 uppercase">
            Drafts you are following
          </h2>
          <ul className="divide-y divide-rule">
            {drafts.map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <InlineName
                    value={d.name || d.id}
                    onRename={(next) => onRename(d.id, next)}
                    activateOn="dblclick"
                    className="-ml-1 block max-w-full text-sm font-medium"
                    inputClassName="w-full text-sm font-medium"
                  />
                  <div className="text-xs text-ink-3">
                    {d.picks_made} picks · {new Date(d.updated_at).toLocaleString()}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onOpen(d.id)}
                  className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(d.id)}
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
