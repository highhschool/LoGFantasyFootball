import { useEffect, useState } from "react";
import { api, ApiError, type AdpProvenance } from "../api";
import { AdpBadge } from "./AdpBadge";
import type { DraftSession, Player } from "../types";
import { BoardGrid } from "./BoardGrid";
import { PickClock } from "./PickClock";
import { InlineName } from "./InlineName";
import { PlayerTable } from "./PlayerTable";
import { RosterPanel } from "./RosterPanel";

// The board's share of the main column: at the first pick, and once every
// cell is filled. It never takes more than the larger share, because the
// player list is what you actually act on.
const BOARD_MIN_SHARE = 0.25;
const BOARD_MAX_SHARE = 0.44;

interface Props {
  adp?: AdpProvenance;
  session: DraftSession;
  onSession: (session: DraftSession) => void;
  onExit: () => void;
}

export function Draft({ session, onSession, onExit, adp }: Props) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  // Shown by default: the board is the thing you glance at between picks,
  // and it starts small enough not to crowd the list.
  const [showBoard, setShowBoard] = useState(true);
  // Widen: the board spans the full width and everything else stacks under
  // it, for when you want to read the whole board rather than pick from it.
  const [wideBoard, setWideBoard] = useState(false);

  // Re-fetch whenever the board moves or the filters change. Debounced so
  // typing a name does not fire a request per keystroke.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      api
        .available(session.id, { position, search, limit: 1000 })
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

  // Board-to-list split, weighted by how much of the board actually holds
  // picks. Expressed as the board's share of the column rather than as grow
  // ratios, so the two numbers below are the thing you actually want to tune.
  const filled =
    session.picks.length / (session.config.teams * session.config.rounds);
  const boardShare = BOARD_MIN_SHARE + (BOARD_MAX_SHARE - BOARD_MIN_SHARE) * filled;
  const boardGrow = boardShare;
  const listGrow = 1 - boardShare;

  return (
    <div className="flex h-full flex-col">
      <Header
        session={session}
        busy={busy}
        onExit={onExit}
        adp={adp}
        onRename={(name) => act(() => api.updateSession(session.id, { name }))}
        onExpire={() => {
          // Only autopick if it is still genuinely our turn; a slow request
          // could otherwise fire this after the board already moved on.
          if (session.your_turn && !session.complete && !busy) {
            act(() => api.autopick(session.id));
          }
        }}
      />

      {error && (
        <p className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div
        className={
          wideBoard
            ? "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4"
            : "grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]"
        }
      >
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
              onClick={() => {
                // Hiding the board also hides the widen control, so leaving
                // wide mode on would strand the layout with no way back.
                if (showBoard) setWideBoard(false);
                setShowBoard((v) => !v);
              }}
              className="ml-auto rounded-md bg-raised px-3 py-1.5 text-sm font-medium"
            >
              {showBoard ? "Hide board" : "Show board"}
            </button>
            {showBoard && (
              <button
                type="button"
                onClick={() => setWideBoard((v) => !v)}
                aria-pressed={wideBoard}
                title={
                  wideBoard
                    ? "Narrow the board and put the roster back alongside"
                    : "Widen the board to full width, roster underneath"
                }
                aria-label={wideBoard ? "Narrow the board" : "Widen the board"}
                className="rounded-md bg-raised px-3 py-1.5 text-sm font-medium"
              >
                {wideBoard ? "«" : "»"}
              </button>
            )}
          </div>

          {/* The board earns its space as it fills. Empty it is mostly blank
              rows, so it starts small and the list keeps the room; by the end
              it holds 180 picks worth of reference and takes the larger share.
              Both scroll internally rather than pushing the other off screen. */}
          {showBoard && (
            <BoardGrid
              session={session}
              style={wideBoard ? undefined : { flexGrow: boardGrow }}
              className={
                wideBoard
                  ? "h-[58vh] min-h-64 shrink-0"
                  : "min-h-24 basis-0 motion-safe:transition-[flex-grow] motion-safe:duration-500"
              }
            />
          )}

          <PlayerTable
            players={players}
            loading={loading}
            disabled={locked}
            search={search}
            position={position}
            onSearch={setSearch}
            onPosition={setPosition}
            onDraft={(p) => act(() => api.pick(session.id, p.key))}
            style={showBoard && !wideBoard ? { flexGrow: listGrow } : undefined}
            className={
              wideBoard
                ? "h-[55vh] min-h-72 shrink-0"
                : showBoard
                  ? "min-h-40 basis-0 motion-safe:transition-[flex-grow] motion-safe:duration-500"
                  : "flex-1"
            }
          />
        </div>

        {wideBoard ? (
          <RosterPanel
            session={session}
            className="grid shrink-0 gap-3 md:grid-cols-2 xl:grid-cols-3"
          />
        ) : (
          <div className="min-h-0 overflow-y-auto">
            <RosterPanel session={session} />
          </div>
        )}
      </div>
    </div>
  );
}

function Header({
  session,
  busy,
  onExit,
  adp,
  onRename,
  onExpire,
}: {
  session: DraftSession;
  busy: boolean;
  onExit: () => void;
  adp?: AdpProvenance;
  onRename: (name: string) => void;
  onExpire: () => void;
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

      <InlineName
        value={session.name}
        onRename={onRename}
        className="max-w-52 text-sm font-semibold"
        inputClassName="min-w-32 text-sm font-semibold"
      />

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

          <PickClock
            seconds={session.pick_seconds}
            active={session.your_turn && !busy}
            resetKey={session.picks.length}
            onExpire={onExpire}
          />
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <AdpBadge adp={adp} />
        <span className="tnum text-sm text-ink-3">
          {session.picks.length}/{session.config.teams * session.config.rounds} picks
        </span>
      </div>
    </header>
  );
}
