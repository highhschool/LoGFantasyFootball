import { useCallback, useEffect, useRef, useState } from "react";
import { live } from "../api";
import type { Advice, LiveDraft } from "../types";
import { AdvicePanel } from "./AdvicePanel";
import { BoardGrid } from "./BoardGrid";
import { InlineName } from "./InlineName";
import { RosterPanel } from "./RosterPanel";

const POLL_MS = 3000;

interface Props {
  draft: LiveDraft;
  onDraft: (draft: LiveDraft) => void;
  onRename: (name: string) => void;
  onExit: () => void;
}

export function LiveDraftView({ draft, onDraft, onRename, onExit }: Props) {
  const [advice, setAdvice] = useState<Advice[]>([]);
  const [advising, setAdvising] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const inFlight = useRef(false);

  const sync = useCallback(async () => {
    // A slow response must not stack up behind the interval.
    if (inFlight.current) return;
    inFlight.current = true;
    setSyncing(true);
    try {
      onDraft(await live.sync(draft.id));
      setLastSync(new Date());
    } catch {
      // The server returns the board it has with sync_error attached, so a
      // genuine failure here means the app is unreachable, not Sleeper.
    } finally {
      inFlight.current = false;
      setSyncing(false);
    }
  }, [draft.id, onDraft]);

  useEffect(() => {
    if (draft.complete) return;

    const timer = setInterval(() => {
      // No point polling a draft nobody is looking at.
      if (document.visibilityState === "visible") sync();
    }, POLL_MS);

    // Catch up immediately on returning to the tab rather than waiting.
    const onVisible = () => {
      if (document.visibilityState === "visible") sync();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [draft.complete, sync]);

  useEffect(() => {
    let cancelled = false;
    setAdvising(true);
    live
      .advice(draft.id)
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
  }, [draft.id, draft.picks.length]);

  const clock = draft.on_the_clock;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule bg-surface px-4 py-3">
        <button
          type="button"
          onClick={onExit}
          className="text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Drafts
        </button>

        <div className="h-5 w-px bg-rule" />

        <InlineName
          value={draft.name}
          onRename={onRename}
          className="max-w-52 text-sm font-semibold"
          inputClassName="min-w-32 text-sm font-semibold"
        />

        <div className="h-5 w-px bg-rule" />

        {draft.complete ? (
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

            {draft.your_turn ? (
              <span className="rounded-md bg-accent px-2.5 py-1 text-sm font-semibold text-ground">
                You're on the clock
              </span>
            ) : (
              <span className="text-sm text-ink-3">Team {clock?.team_slot} picking</span>
            )}

            {draft.picks_until_your_next !== null && !draft.your_turn && (
              <span className="tnum text-sm text-ink-3">
                {draft.picks_until_your_next} picks until your turn
              </span>
            )}
          </>
        )}

        <div className="ml-auto flex items-center gap-3">
          <SyncStatus
            syncing={syncing}
            complete={draft.complete}
            error={draft.sync_error}
            at={lastSync}
          />
          <button
            type="button"
            onClick={sync}
            disabled={syncing}
            className="rounded-md bg-raised px-3 py-1.5 text-sm font-medium disabled:opacity-40"
          >
            Refresh
          </button>
        </div>
      </header>

      {draft.sync_error && (
        <p className="border-b border-warn/40 bg-warn-soft px-4 py-2 text-sm text-warn">
          Sleeper is not responding, so the board may be behind. Showing the
          last picks we received; it will catch up on its own.
        </p>
      )}

      {draft.unranked.length > 0 && (
        <p className="border-b border-rule bg-raised px-4 py-2 text-sm text-ink-2">
          {draft.unranked.length === 1 ? "One pick is" : `${draft.unranked.length} picks are`}{" "}
          outside the rankings and have no ADP behind them:{" "}
          {draft.unranked.map((u) => u.name).join(", ")}. They still hold their
          place on the board.
        </p>
      )}

      <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 lg:overflow-hidden lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <BoardGrid session={draft} className="h-[50dvh] shrink-0 lg:h-auto lg:min-h-0 lg:shrink lg:flex-1" />
        <div className="flex flex-col gap-3 lg:min-h-0 lg:overflow-y-auto">
          {/* No draft button: the pick is made on Sleeper, not here. */}
          <AdvicePanel advice={advice} loading={advising} yourTurn={draft.your_turn} />
          <RosterPanel session={draft} />
        </div>
      </div>
    </div>
  );
}

function SyncStatus({
  syncing,
  complete,
  error,
  at,
}: {
  syncing: boolean;
  complete: boolean;
  error?: string;
  at: Date | null;
}) {
  if (complete) {
    return <span className="text-xs text-ink-3">No longer updating</span>;
  }
  if (error) {
    return <span className="text-xs text-warn">Reconnecting…</span>;
  }
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-3">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          syncing ? "bg-accent" : "bg-rule"
        }`}
      />
      {at ? `Updated ${at.toLocaleTimeString()}` : "Watching for picks"}
    </span>
  );
}
