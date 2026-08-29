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
export const SPEEDS = {
  instant: { label: "Instant", pause: 0 },
  slow: { label: "Slow", pause: 1800 },
  normal: { label: "Normal", pause: 900 },
  fast: { label: "Fast", pause: 350 },
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
      {(Object.keys(SPEEDS) as Speed[]).map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          className={`rounded-md px-2 py-1 text-xs font-medium ${
            key === speed ? "bg-accent text-ground" : "bg-raised text-ink-2 hover:text-ink"
          }`}
        >
          {SPEEDS[key].label}
        </button>
      ))}

      {running && (
        <button
          type="button"
          onClick={onSkip}
          className="ml-1 rounded-md bg-raised px-2 py-1 text-xs font-semibold text-ink-2"
        >
          Skip to my pick
        </button>
      )}
    </div>
  );
}
