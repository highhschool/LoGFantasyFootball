import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { DraftSession, Player } from "../types";
import { BoardGrid } from "./BoardGrid";
import { PlayerTable } from "./PlayerTable";
import { RosterPanel } from "./RosterPanel";

interface Props {
  session: DraftSession;
  onSession: (session: DraftSession) => void;
  onExit: () => void;
}

export function Draft({ session, onSession, onExit }: Props) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  const [showBoard, setShowBoard] = useState(false);

  // Re-fetch whenever the board moves or the filters change. Debounced so
  // typing a name does not fire a request per keystroke.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      api
        .available(session.id, { position, search, limit: 100 })
        .then((next) => {
          if (!cancelled) setPlayers(next);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, search ? 200 : 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [session.id, session.picks.length, position, search]);

  async function act(fn: () => Promise<DraftSession>) {
    setBusy(true);
    setError(null);
    try {
      onSession(await fn());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const locked = busy || session.complete || !session.your_turn;

  return (
    <div className="flex h-full flex-col">
      <Header session={session} busy={busy} onExit={onExit} />

      {error && (
        <p className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <div className="flex min-h-0 flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={locked}
              onClick={() => act(() => api.autopick(session.id))}
              className="rounded-md bg-raised px-3 py-1.5 text-sm font-medium disabled:opacity-40"
            >
              Autopick
            </button>
            <button
              type="button"
              disabled={busy || session.picks.length === 0}
              onClick={() => act(() => api.undo(session.id))}
              className="rounded-md bg-raised px-3 py-1.5 text-sm font-medium disabled:opacity-40"
            >
              Undo my last pick
            </button>
            <button
              type="button"
              disabled={busy || session.complete}
              onClick={() => act(() => api.simulate(session.id))}
              className="rounded-md bg-raised px-3 py-1.5 text-sm font-medium disabled:opacity-40"
            >
              Simulate to end
            </button>
            <button
              type="button"
              onClick={() => setShowBoard((v) => !v)}
              className="ml-auto rounded-md bg-raised px-3 py-1.5 text-sm font-medium"
            >
              {showBoard ? "Hide board" : "Show board"}
            </button>
          </div>

          {showBoard && <BoardGrid session={session} />}

          <PlayerTable
            players={players}
            loading={loading}
            disabled={locked}
            search={search}
            position={position}
            onSearch={setSearch}
            onPosition={setPosition}
            onDraft={(p) => act(() => api.pick(session.id, p.key))}
          />
        </div>

        <div className="min-h-0 overflow-y-auto">
          <RosterPanel session={session} />
        </div>
      </div>
    </div>
  );
}

function Header({
  session,
  busy,
  onExit,
}: {
  session: DraftSession;
  busy: boolean;
  onExit: () => void;
}) {
  const clock = session.on_the_clock;

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule bg-surface px-4 py-3">
      <button
        type="button"
        onClick={onExit}
        className="text-sm font-medium text-ink-3 hover:text-ink"
      >
        ← Sessions
      </button>

      <div className="h-5 w-px bg-rule" />

      {session.complete ? (
        <span className="rounded-md bg-accent-soft px-2.5 py-1 text-sm font-semibold text-accent">
          Draft complete
        </span>
      ) : (
        <>
          <span className="tnum text-sm text-ink-2">
            Round <strong className="text-ink">{clock?.round}</strong> · Pick{" "}
            <strong className="text-ink">{clock?.pick_in_round}</strong>
            <span className="text-ink-3"> (overall {clock?.overall})</span>
          </span>

          {session.your_turn ? (
            <span className="rounded-md bg-accent px-2.5 py-1 text-sm font-semibold text-ground">
              {busy ? "Working…" : "You're on the clock"}
            </span>
          ) : (
            <span className="text-sm text-ink-3">
              Team {clock?.team_slot} picking
            </span>
          )}

          {session.picks_until_your_next !== null && !session.your_turn && (
            <span className="tnum text-sm text-ink-3">
              {session.picks_until_your_next} picks until your turn
            </span>
          )}
        </>
      )}

      <span className="tnum ml-auto text-sm text-ink-3">
        {session.picks.length}/{session.config.teams * session.config.rounds} picks
      </span>
    </header>
  );
}
