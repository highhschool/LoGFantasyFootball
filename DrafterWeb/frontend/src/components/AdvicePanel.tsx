import type { Advice } from "../types";
import { PositionBadge } from "./PositionBadge";

interface Props {
  advice: Advice[];
  loading: boolean;
  /** Mock drafts can act on a suggestion; a live board is picked on Sleeper. */
  onDraft?: (advice: Advice) => void;
  canDraft?: boolean;
  yourTurn: boolean;
}

export function AdvicePanel({ advice, loading, onDraft, canDraft, yourTurn }: Props) {
  if (!loading && advice.length === 0) return null;

  return (
    <section className="rounded-lg border border-rule bg-surface">
      <h2 className="flex items-baseline gap-2 border-b border-rule px-3 py-2">
        <span className="text-xs font-semibold tracking-wider text-ink-3 uppercase">
          Recommended
        </span>
        {!yourTurn && (
          <span className="text-[11px] text-ink-3">if you were picking now</span>
        )}
      </h2>

      {loading && advice.length === 0 ? (
        <p className="px-3 py-4 text-sm text-ink-3">Thinking…</p>
      ) : (
        <ol className="divide-y divide-rule">
          {advice.map((a, i) => (
            <li key={a.key} className="flex gap-2.5 px-3 py-2.5">
              <span className="tnum w-4 pt-0.5 text-xs font-semibold text-ink-3">
                {i + 1}
              </span>

              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <PositionBadge position={a.position} />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {a.name}
                  </span>
                  <span className="tnum text-xs text-ink-3">
                    {a.team}
                    {a.bye_week !== null && ` · bye ${a.bye_week}`}
                  </span>
                </div>

                <ul className="flex flex-col gap-0.5">
                  {a.reasons.map((reason) => (
                    <li key={reason} className="text-xs text-ink-2">
                      {reason}
                    </li>
                  ))}
                </ul>

                <div className="flex items-center gap-2">
                  <Availability advice={a} />
                  <span className="tnum text-[11px] text-ink-3">
                    ADP {a.adp.toFixed(1)}
                  </span>

                  {onDraft && (
                    <button
                      type="button"
                      disabled={!canDraft}
                      onClick={() => onDraft(a)}
                      className="ml-auto rounded bg-accent px-2 py-0.5 text-[11px] font-semibold text-ground disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Draft
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Whether he will still be there next turn.
 *
 * The reported ADP spread is tight, so most of the board is gone by your next
 * pick and saying so every time explains nothing. It earns a chip rather than
 * a sentence, and only the ones you can wait on get the accent.
 */
function Availability({ advice }: { advice: Advice }) {
  if (advice.gone_by_next) {
    return (
      <span className="rounded bg-raised px-1.5 py-0.5 text-[11px] text-ink-3">
        gone by your next pick
      </span>
    );
  }
  return (
    <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">
      {Math.round(advice.survival * 100)}% to last
    </span>
  );
}
