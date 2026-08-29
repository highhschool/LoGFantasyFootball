import { useState } from "react";
import type { Advice } from "../types";
import { PlayerProfile } from "./PlayerProfile";
import { PositionBadge } from "./PositionBadge";

interface Props {
  advice: Advice[];
  loading: boolean;
  /** Mock drafts can act on a suggestion; a live board is picked on Sleeper. */
  onDraft?: (advice: Advice) => void;
  canDraft?: boolean;
  yourTurn: boolean;
  /** Your next pick, so a profile can say whether he survives to it. */
  atPick?: number;
}

export function AdvicePanel({
  advice,
  loading,
  onDraft,
  canDraft,
  yourTurn,
  atPick,
}: Props) {
  const [profile, setProfile] = useState<number | null>(null);

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
        {advice.length > 0 && (
          <span className="ml-auto text-[11px] text-ink-3">
            {advice[0].starters_left === 0
              ? "lineup full"
              : `${advice[0].starters_left} starting ${
                  advice[0].starters_left === 1 ? "spot" : "spots"
                } to fill`}
          </span>
        )}
      </h2>

      {loading && advice.length === 0 ? (
        <p className="px-3 py-4 text-sm text-ink-3">Thinking…</p>
      ) : (
        <ol className="divide-y divide-rule">
          {advice.map((a, i) => (
            <li
              key={a.key}
              role="button"
              tabIndex={0}
              onClick={() => setProfile(a.ffc_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setProfile(a.ffc_id);
                }
              }}
              title="Career, ADP and the latest on him"
              className="flex cursor-pointer gap-2.5 px-3 py-2.5 hover:bg-raised focus-visible:bg-raised focus-visible:outline-none"
            >
              <span className="tnum w-4 pt-0.5 text-xs font-semibold text-ink-3">
                {i + 1}
              </span>

              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <PositionBadge position={a.position} />
                  <SlotMark slot={a.slot} />
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

                <div className="flex flex-wrap items-center gap-2">
                  <Pressure advice={a} />
                  <span className="tnum text-[11px] text-ink-3">
                    ADP {a.adp.toFixed(1)}
                  </span>

                  {onDraft && (
                    <button
                      type="button"
                      disabled={!canDraft}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDraft(a);
                      }}
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

      {profile !== null && (
        <PlayerProfile
          ffcId={profile}
          atPick={atPick}
          onClose={() => setProfile(null)}
        />
      )}
    </section>
  );
}

/**
 * What waiting a turn costs at this position.
 *
 * The decisive fact is not whether this player survives -- with the ADP spread
 * as tight as it is, almost nobody does -- but how far the position falls
 * before you pick again. A position that keeps is the one to skip.
 */
function Pressure({ advice }: { advice: Advice }) {
  if (advice.dropoff < 3) {
    return (
      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">
        holds up
      </span>
    );
  }

  const steep = advice.dropoff >= 12;
  return (
    <span
      className={`tnum rounded px-1.5 py-0.5 text-[11px] font-medium ${
        steep ? "bg-warn-soft text-warn" : "bg-raised text-ink-2"
      }`}
      title={`Wait a turn and the best ${advice.position} left is likely ${advice.alternative} (ADP ${advice.alternative_adp.toFixed(1)})`}
    >
      −{Math.round(advice.dropoff)} picks if you wait
    </span>
  );
}

/**
 * Where the pick would land in your lineup.
 *
 * The distinction the advisor was missing entirely: a first running back
 * fills a starting slot and a fifth sits behind four others, and until this
 * existed they were weighted alike.
 */
function SlotMark({ slot }: { slot: Advice["slot"] }) {
  if (slot === "starter") {
    return (
      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-accent uppercase">
        starts
      </span>
    );
  }
  if (slot === "flex") {
    return (
      <span className="rounded bg-raised px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-ink-2 uppercase">
        flex
      </span>
    );
  }
  return (
    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-ink-3 uppercase">
      bench
    </span>
  );
}
