import { useEffect, useState } from "react";
import { api, ApiError, type AdpProvenance } from "../api";
import { AdpBadge } from "./AdpBadge";
import type { Advice, DraftSession, Player } from "../types";
import { AdvicePanel } from "./AdvicePanel";
import { BoardGrid } from "./BoardGrid";
import { PickClock } from "./PickClock";
import { InlineName } from "./InlineName";
import { PlayerTable } from "./PlayerTable";
import { RosterPanel } from "./RosterPanel";
import { VerticalResizer } from "./VerticalResizer";

// The board's share of the main column: at the first pick, and once every
// cell is filled. It never takes more than the larger share, because the
// player list is what you actually act on.
const BOARD_HEIGHT_KEY = "ngfl.boardHeight";
const BOARD_MIN_HEIGHT = 160;
const BOARD_DEFAULT_FRACTION = 0.42;

/** Last dragged height, or a sensible fraction of this viewport. */
function readStoredHeight(): number {
  const fallback = Math.round(window.innerHeight * BOARD_DEFAULT_FRACTION);
  try {
    const stored = Number(localStorage.getItem(BOARD_HEIGHT_KEY));
    return Number.isFinite(stored) && stored >= BOARD_MIN_HEIGHT ? stored : fallback;
  } catch {
    return fallback;
  }
}

/** Leaves room for the player list and roster below. */
function maxBoardHeightFor(viewportHeight: number): number {
  return Math.max(BOARD_MIN_HEIGHT, viewportHeight - 320);
}

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
  const [advice, setAdvice] = useState<Advice[]>([]);
  const [advising, setAdvising] = useState(true);
  const [showBoard, setShowBoard] = useState(true);
  // Widen: the board spans the full width and everything else stacks under
  // it, for when you want to read the whole board rather than pick from it.
  const [wideBoard, setWideBoard] = useState(false);
  const [boardHeight, setBoardHeight] = useState(readStoredHeight);

  // Remember where the divider was left. Wrapped because storage throws
  // outright in some privacy modes rather than just returning nothing.
  useEffect(() => {
    try {
      localStorage.setItem(BOARD_HEIGHT_KEY, String(boardHeight));
    } catch {
      // Not worth surfacing; the layout simply will not persist.
    }
  }, [boardHeight]);

  // A height that fit a tall window would overflow a short one, so pull it
  // back in when the viewport shrinks.
  useEffect(() => {
    function clampToViewport() {
      setBoardHeight((h) => Math.min(h, maxBoardHeightFor(window.innerHeight)));
    }
    clampToViewport();
    window.addEventListener("resize", clampToViewport);
    return () => window.removeEventListener("resize", clampToViewport);
  }, []);

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

  useEffect(() => {
    let cancelled = false;
    setAdvising(true);
    api
      .advice(session.id)
      .then((next) => {
        if (!cancelled) setAdvice(next);
      })
      .catch(() => {
        if (!cancelled) setAdvice([]);
      })
      .finally(() => {
        if (!cancelled) setAdvising(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session.id, session.picks.length]);

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
  const maxBoardHeight = maxBoardHeightFor(window.innerHeight);
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

      {/* The toolbar spans the view; only the board moves between layouts.
          Widened it sits full width above both columns, so the player list and
          roster stay side by side underneath rather than stacking. */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 lg:overflow-hidden">
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
              // Hiding the board also hides the widen control, so leaving wide
              // mode on would strand the layout with no way back.
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
                  ? "Narrow the board back into the left column"
                  : "Widen the board across the full width"
              }
              aria-label={wideBoard ? "Narrow the board" : "Widen the board"}
              className="hidden rounded-md bg-raised px-3 py-1.5 text-sm font-medium lg:inline-flex"
            >
              {wideBoard ? "«" : "»"}
            </button>
          )}
        </div>

        {showBoard && wideBoard && (
          <>
            <BoardGrid
              session={session}
              style={{ height: boardHeight }}
              className="shrink-0"
            />
            <VerticalResizer
              height={boardHeight}
              onHeight={setBoardHeight}
              min={BOARD_MIN_HEIGHT}
              max={maxBoardHeight}
              label="Resize the draft board"
            />
          </>
        )}

        <div className="grid gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
          <div className="flex flex-col gap-3 lg:min-h-0">
            {/* Narrow, the board earns its height as it fills: empty it is
                mostly blank rows, so the list keeps the room early on. */}
            {showBoard && !wideBoard && (
              <BoardGrid
                session={session}
                style={{ flexGrow: boardGrow }}
                className="h-[48dvh] shrink-0 lg:h-auto lg:min-h-24 lg:shrink lg:basis-0 lg:motion-safe:transition-[flex-grow] lg:motion-safe:duration-500"
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
                showBoard && !wideBoard
                  ? "h-[60dvh] shrink-0 lg:h-auto lg:min-h-40 lg:shrink lg:basis-0 lg:motion-safe:transition-[flex-grow] lg:motion-safe:duration-500"
                  : "h-[70dvh] shrink-0 lg:h-auto lg:shrink lg:flex-1"
              }
            />
          </div>

          <div className="flex flex-col gap-3 lg:min-h-0 lg:overflow-y-auto">
            <AdvicePanel
              advice={advice}
              loading={advising}
              yourTurn={session.your_turn}
              canDraft={!locked}
              onDraft={(a) => act(() => api.pick(session.id, a.key))}
            />
            <RosterPanel session={session} />
          </div>
        </div>
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
