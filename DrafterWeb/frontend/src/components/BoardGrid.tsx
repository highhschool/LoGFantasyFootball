import type { BoardView, Position } from "../types";

const TONE: Record<string, string> = {
  QB: "text-qb",
  RB: "text-rb",
  WR: "text-wr",
  TE: "text-te",
  K: "text-k",
  DST: "text-dst",
};

/**
 * The whole draft, one cell per pick, snake order left to right.
 *
 * Fills its container and scrolls internally, with the round column and team
 * header pinned -- on a 15x12 board you are almost always looking at a cell
 * whose row or column label has scrolled out of view.
 */
export function BoardGrid({
  session,
  className = "",
  style,
}: {
  session: BoardView;
  className?: string;
  style?: React.CSSProperties;
}) {
  const { teams, rounds, your_slot } = session.config;
  const byOverall = new Map(session.picks.map((p) => [p.overall, p]));
  const onClock = session.on_the_clock?.overall ?? -1;
  const slots = Array.from({ length: teams }, (_, i) => i + 1);

  return (
    <section
      style={style}
      className={`flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-rule bg-surface ${className}`}
    >
      <header className="flex items-center gap-3 border-b border-rule px-3 py-2">
        <h2 className="text-xs font-semibold tracking-wider text-ink-3 uppercase">
          Draft board
        </h2>
        <span className="tnum text-xs text-ink-3">
          {session.picks.length} of {teams * rounds} picks
        </span>
        <Legend />
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              <th className="sticky top-0 left-0 z-30 w-10 border-r border-b border-rule bg-raised px-2 py-2 text-ink-3">
                Rd
              </th>
              {slots.map((slot) => (
                <th
                  key={slot}
                  className={`sticky top-0 z-20 min-w-28 border-b border-rule px-2 py-2 font-semibold ${
                    slot === your_slot
                      ? "bg-accent-soft text-accent"
                      : "bg-raised text-ink-3"
                  }`}
                >
                  {slot === your_slot ? "YOU" : `Team ${slot}`}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {Array.from({ length: rounds }, (_, r) => {
              const round = r + 1;
              const ascending = round % 2 === 1;

              return (
                <tr key={round}>
                  <th className="sticky left-0 z-10 border-r border-b border-rule bg-raised px-2 py-2 text-center font-medium text-ink-3">
                    {round}
                  </th>

                  {slots.map((slot) => {
                    // Snake: odd rounds run left to right, even rounds reverse,
                    // so a slot's position within the round flips each round.
                    const indexInRound = ascending ? slot - 1 : teams - slot;
                    const overall = r * teams + indexInRound + 1;
                    const pick = byOverall.get(overall);
                    const isClock = overall === onClock;
                    const mine = slot === your_slot;

                    return (
                      <td
                        key={slot}
                        className={`border-b border-rule px-2 py-1.5 align-top ${
                          mine ? "bg-accent-soft/40" : ""
                        } ${isClock ? "ring-2 ring-accent ring-inset" : ""}`}
                      >
                        {pick ? (
                          <div className="flex flex-col gap-0.5">
                            <span className="truncate font-medium text-ink" title={pick.player_name}>
                              {pick.player_name}
                            </span>
                            <span className="flex items-center gap-1.5">
                              <span className={`font-semibold ${TONE[pick.position] ?? ""}`}>
                                {pick.position}
                              </span>
                              <span className="text-ink-3">{pick.team}</span>
                              {pick.source === "keeper" && (
                                <span className="rounded bg-warn-soft px-1 text-[10px] font-semibold text-warn">
                                  K
                                </span>
                              )}
                            </span>
                          </div>
                        ) : (
                          <span
                            className={`tnum ${isClock ? "font-semibold text-accent" : "text-ink-3/60"}`}
                          >
                            {isClock ? "on the clock" : overall}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Legend() {
  const positions: Position[] = ["QB", "RB", "WR", "TE", "K", "DST"];
  return (
    <div className="ml-auto hidden items-center gap-2.5 sm:flex">
      {positions.map((p) => (
        <span key={p} className={`text-[11px] font-semibold ${TONE[p]}`}>
          {p}
        </span>
      ))}
    </div>
  );
}
