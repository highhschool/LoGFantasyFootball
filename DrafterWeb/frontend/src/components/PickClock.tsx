import { useEffect, useRef, useState } from "react";

interface Props {
  seconds: number;        // 0 disables the clock
  active: boolean;        // only runs while it is your pick
  resetKey: number | string;
  onExpire: () => void;
}

/**
 * The on-the-clock countdown.
 *
 * Counts against wall time rather than accumulating setInterval ticks, so a
 * backgrounded tab (which browsers throttle to roughly once a second, or less)
 * still shows the true remaining time when you come back to it.
 *
 * On expiry it fires once and stops. Autopicking is the honest analogue of a
 * real draft, where missing your clock does not skip you -- it picks for you.
 */
export function PickClock({ seconds, active, resetKey, onExpire }: Props) {
  const [left, setLeft] = useState(seconds);
  const fired = useRef(false);
  const expire = useRef(onExpire);
  expire.current = onExpire;

  useEffect(() => {
    if (!active || seconds <= 0) {
      setLeft(seconds);
      fired.current = false;
      return;
    }

    fired.current = false;
    const deadline = Date.now() + seconds * 1000;
    setLeft(seconds);

    const tick = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0 && !fired.current) {
        fired.current = true;
        clearInterval(tick);
        expire.current();
      }
    }, 250);

    return () => clearInterval(tick);
  }, [active, seconds, resetKey]);

  if (seconds <= 0) return null;

  const urgent = active && left <= 10;
  const warning = active && left <= 30 && left > 10;

  return (
    <span
      role="timer"
      aria-live={urgent ? "assertive" : "off"}
      className={`tnum inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-semibold ${
        !active
          ? "bg-raised text-ink-3"
          : urgent
            ? "bg-danger/15 text-danger"
            : warning
              ? "bg-warn-soft text-warn"
              : "bg-raised text-ink-2"
      }`}
      title={active ? "Time left on your pick" : "Pick clock (paused)"}
    >
      {format(active ? left : seconds)}
    </span>
  );
}

function format(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
