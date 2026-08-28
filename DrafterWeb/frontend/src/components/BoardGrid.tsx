import type { DraftSession } from "../types";

const TONE: Record<string, string> = {
  QB: "text-qb",
  RB: "text-rb",
  WR: "text-wr",
  TE: "text-te",
  K: "text-k",
  DST: "text-dst",
};

/** The whole draft, one cell per pick, snake order left to right. */
export function BoardGrid({ session }: { session: DraftSession }) {
  const { teams, rounds, your_slot } = session.config;
  const byOverall = new Map(session.picks.map((p) => [p.overall, p]));
  const onClock = session.on_the_clock?.overall ?? -1;

  const rows = Array.from({ length: rounds }, (_, r) => {
    const round = r + 1;
    const ascending = round % 2 === 1;
    return Array.from({ length: teams }, (_, i) => {
      const slot = ascending ? i + 1 : teams - i;
      return { overall: r * teams + i + 1, slot, round };
    });
  });

  return (
    <div className="overflow-x-auto rounded-lg border border-rule bg-surface">
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-raised px-2 py-1.5 text-ink-3">R</th>
            {Array.from({ length: teams }, (_, i) => i + 1).map((slot) => (
              <th
                key={slot}
                className={`min-w-24 px-2 py-1.5 font-semibold ${
                  slot === your_slot ? "bg-accent-soft text-accent" : "bg-raised text-ink-3"
                }`}
              >
                {slot === your_slot ? "YOU" : slot}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, r) => (
            <tr key={r} className="border-t border-rule">
              <td className="sticky left-0 z-10 bg-raised px-2 py-1 text-center text-ink-3">
                {r + 1}
              </td>
              {/* Render by slot, not pick order, so columns stay aligned. */}
              {Array.from({ length: teams }, (_, i) => i + 1).map((slot) => {
                const cell = cells.find((c) => c.slot === slot)!;
                const pick = byOverall.get(cell.overall);
                const isClock = cell.overall === onClock;
                const mine = slot === your_slot;

                return (
                  <td
                    key={slot}
                    className={`px-2 py-1 align-top ${mine ? "bg-accent-soft/40" : ""} ${
                      isClock ? "ring-2 ring-accent ring-inset" : ""
                    }`}
                  >
                    {pick ? (
                      <div className="truncate">
                        <span className={`font-semibold ${TONE[pick.position] ?? ""}`}>
                          {pick.position}
                        </span>{" "}
                        <span className="text-ink-2">{lastName(pick.player_name)}</span>
                      </div>
                    ) : (
                      <span className="tnum text-ink-3">{cell.overall}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function lastName(full: string): string {
  const parts = full.split(" ");
  return parts.length > 1 ? parts.slice(1).join(" ") : full;
}
