/**
 * How fast the bots pick.
 *
 * A mock draft that jumps straight back to your turn tells you what happened
 * but never lets you watch it happen -- and watching the board fill is most of
 * why anybody runs one. Pacing is purely presentational: every speed produces
 * the same board, because each step is a real pick in the log either way.
 */
// Declaration order is the order they are drawn, running from no wait to the
// longest one rather than jumping about.
//
// The two ends are drawn as chevrons rather than words, so the row reads as a
// scale with Normal in the middle and slower and faster either side of it,
// instead of four labels that have to be compared. They still carry their
// names for anyone reading the page rather than looking at it.
export const SPEEDS = {
  instant: { label: "Instant", name: "Instant", pause: 0 },
  slow: { label: "«", name: "Slow", pause: 900 },
  normal: { label: "Normal", name: "Normal", pause: 350 },
  fast: { label: "»", name: "Fast", pause: 200 },
} as const;

export type Speed = keyof typeof SPEEDS;

export const DEFAULT_SPEED: Speed = "normal";
const REMEMBERED = "ngfl:draft-speed";

/** A gap between picks, jittered so twelve bots do not tick like a metronome. */
export function pauseFor(speed: Speed): number {
  const base = SPEEDS[speed].pause;
  return base ? base * (0.75 + Math.random() * 0.5) : 0;
}

export function rememberedSpeed(): Speed {
  try {
    const held = localStorage.getItem(REMEMBERED);
    if (held && held in SPEEDS) return held as Speed;
  } catch {
    // Private windows and blocked storage. The default is fine.
  }
  return DEFAULT_SPEED;
}

export function rememberSpeed(speed: Speed): void {
  try {
    localStorage.setItem(REMEMBERED, speed);
  } catch {
    // Not worth surfacing; it just will not be remembered.
  }
}

export function SpeedPicker({
  speed,
  onChange,
  running,
  onSkip,
  className = "",
}: {
  speed: Speed;
  onChange: (speed: Speed) => void;
  /** True while bots are picking, so the skip is only offered when it does something. */
  running: boolean;
  onSkip: () => void;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>
      <span className="text-xs text-ink-3">Bots</span>

      {/* Always laid out, only sometimes visible. It used to be appended when
          the bots started picking, which shoved the speeds along and re-wrapped
          the bar underneath -- the controls moved at exactly the moment you
          were reaching for them. Hidden rather than unmounted, so the row is
          the same width whether it is running or not. `invisible` also takes
          it out of the tab order, which `opacity-0` would not. */}
      <button
        type="button"
        onClick={onSkip}
        disabled={!running}
        aria-hidden={!running}
        title="Skip to my pick"
        aria-label="Skip to my pick"
        className={`rounded-md bg-raised px-2 py-1 text-xs font-semibold text-ink-2 hover:text-ink ${
          running ? "" : "invisible"
        }`}
      >
        Skip
      </button>

      {(Object.keys(SPEEDS) as Speed[]).map((key) => {
        const { label, name } = SPEEDS[key];
        const glyph = label !== name;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            // A chevron on its own says nothing to a screen reader, and on a
            // touch screen it is a smaller target than a word -- so it keeps
            // the name and gets padded back out to the width of one.
            aria-label={glyph ? name : undefined}
            title={glyph ? name : undefined}
            className={`rounded-md py-1 text-xs font-medium ${
              glyph ? "w-8 leading-none" : "px-2"
            } ${
              key === speed ? "bg-accent text-ground" : "bg-raised text-ink-2 hover:text-ink"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
