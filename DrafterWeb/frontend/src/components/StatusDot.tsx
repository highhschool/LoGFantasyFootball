/**
 * Whether a market is taking money.
 *
 * Four states, not two. Red-for-closed and green-for-open leaves "hasn't
 * opened yet" and "trading is over" wearing the same colour, which are
 * opposite things to a person deciding whether to come back.
 *
 * The dot never travels alone. Red and green are the pairing most people with
 * colour blindness cannot separate, so the colour is the glance and the word
 * is the answer.
 */
const STATES = {
  open: { tone: "bg-accent", ring: "bg-accent/30", label: "Open" },
  pending: { tone: "bg-warn", ring: "", label: "Not open yet" },
  closed: { tone: "bg-danger", ring: "", label: "Closed" },
  settled: { tone: "bg-ink-3", ring: "", label: "Settled" },
} as const;

export type Phase = keyof typeof STATES;

export function StatusDot({
  phase,
  label = true,
  className = "",
}: {
  phase: Phase;
  /** Off only where the same word already sits beside it. */
  label?: boolean;
  className?: string;
}) {
  const state = STATES[phase] ?? STATES.settled;

  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`} title={state.label}>
      <span className="relative inline-flex h-2 w-2 shrink-0">
        {state.ring && (
          // Only the live state animates. A pulse on a closed market would
          // read as something still happening.
          <span
            className={`absolute inline-flex h-full w-full animate-ping rounded-full ${state.ring}`}
          />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${state.tone}`} />
      </span>
      {label && <span className="text-xs font-medium text-ink-3">{state.label}</span>}
      {!label && <span className="sr-only">{state.label}</span>}
    </span>
  );
}
