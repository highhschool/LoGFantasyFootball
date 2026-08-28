/**
 * Draft position, chosen directly rather than dragged on a slider.
 *
 * Slot choice is the most consequential setting on the page -- it decides
 * whether you turn at 1.01 or 1.12 -- so it gets explicit targets and shows the
 * resulting first-round pick rather than making you infer it.
 */
export function SlotPicker({
  teams,
  slot,
  onChange,
}: {
  teams: number;
  slot: number;
  onChange: (slot: number) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-ink-2">Your draft slot</span>
        <span className="tnum text-xs text-ink-3">
          picks {ordinal(slot)} of {teams}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {Array.from({ length: teams }, (_, i) => i + 1).map((n) => {
          const active = n === slot;
          return (
            <button
              key={n}
              type="button"
              aria-pressed={active}
              aria-label={`Draft slot ${n}`}
              onClick={() => onChange(n)}
              className={`tnum h-9 w-9 rounded-md text-sm font-semibold ${
                active
                  ? "bg-accent text-ground"
                  : "bg-raised text-ink-2 hover:text-ink"
              }`}
            >
              {n}
            </button>
          );
        })}
      </div>

      <p className="text-xs text-ink-3">
        {turnHint(slot, teams)}
      </p>
    </div>
  );
}

function ordinal(n: number): string {
  const suffix = ["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) ? 0 : n % 10] ?? "th";
  return `${n}${suffix}`;
}

/** The wait between back-to-back picks is what a slot actually costs you. */
function turnHint(slot: number, teams: number): string {
  const wait = 2 * (teams - slot) + 1;
  if (slot === 1) {
    return `First off the board, then a ${wait}-pick wait — the longest on the board.`;
  }
  if (slot === teams) {
    return `Last in round 1, but you pick back to back at the turn (${wait}-pick wait).`;
  }
  return `You wait ${wait} picks between your first and second selections.`;
}
