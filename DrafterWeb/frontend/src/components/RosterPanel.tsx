import type { DraftSession } from "../types";
import { PositionBadge } from "./PositionBadge";

export function RosterPanel({ session }: { session: DraftSession }) {
  const clashes = Object.entries(session.bye_clashes);

  return (
    <section className="flex min-h-0 flex-col gap-3">
      <div className="rounded-lg border border-rule bg-surface">
        <h2 className="border-b border-rule px-3 py-2 text-xs font-semibold tracking-wider text-ink-3 uppercase">
          Your roster · {session.your_roster.length}/{session.config.rounds}
        </h2>

        {session.your_roster.length === 0 ? (
          <p className="px-3 py-4 text-sm text-ink-3">Nothing drafted yet.</p>
        ) : (
          <ul className="divide-y divide-rule">
            {session.your_roster.map((spot, i) => (
              <li key={`${spot.player_name}-${i}`} className="flex items-center gap-2 px-3 py-1.5">
                <span className="tnum w-6 text-xs text-ink-3">R{spot.round}</span>
                <PositionBadge position={spot.position} />
                <span className="min-w-0 flex-1 truncate text-sm">{spot.player_name}</span>
                {spot.bye_week !== null && (
                  <span className="tnum text-xs text-ink-3">bye {spot.bye_week}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-rule bg-surface">
        <h2 className="border-b border-rule px-3 py-2 text-xs font-semibold tracking-wider text-ink-3 uppercase">
          Still needed
        </h2>
        <ul className="grid grid-cols-3 gap-px bg-rule">
          {Object.entries(session.your_needs).map(([position, remaining]) => (
            <li
              key={position}
              className="flex flex-col items-center gap-0.5 bg-surface px-2 py-2"
            >
              <span className="text-[11px] font-semibold tracking-wide text-ink-3">
                {position}
              </span>
              <span
                className={`tnum text-lg leading-none font-semibold ${
                  remaining === 0 ? "text-ink-3" : "text-ink"
                }`}
              >
                {remaining}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {clashes.length > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2.5">
          <h2 className="text-xs font-semibold tracking-wider text-warn uppercase">
            Bye week stacking
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            {clashes
              .map(([week, count]) => `${count} players share week ${week}`)
              .join("; ")}
            .
          </p>
        </div>
      )}

      {session.unresolved_keepers.length > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2.5">
          <h2 className="text-xs font-semibold tracking-wider text-warn uppercase">
            Keepers not found
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            {session.unresolved_keepers.join(", ")} — spelled differently in this
            season's rankings. The draft is unaffected.
          </p>
        </div>
      )}
    </section>
  );
}
