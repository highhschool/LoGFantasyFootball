import { useEffect, useState } from "react";

/**
 * Time left before a deadline.
 *
 * A weekday and a time answer "when", not "how long" -- and how long is the
 * part that decides whether you deal with it now or later. Seconds only appear
 * inside the last hour, where they mean something; above that they are just
 * motion.
 */
export function Countdown({
  until,
  onExpire,
}: {
  until: string;
  onExpire?: () => void;
}) {
  const target = new Date(until).getTime();
  const [left, setLeft] = useState(() => target - Date.now());

  useEffect(() => {
    const tick = () => setLeft(target - Date.now());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [target]);

  const done = left <= 0;
  useEffect(() => {
    // Let the page find out the deadline passed on its own, rather than
    // leaving somebody looking at an open form that will refuse them.
    if (done) onExpire?.();
  }, [done, onExpire]);

  if (done) return null;

  const total = Math.floor(left / 1000);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;

  const parts = days
    ? [`${days}d`, `${hours}h`, `${minutes}m`]
    : hours
      ? [`${hours}h`, `${minutes}m`, `${seconds}s`]
      : [`${minutes}m`, `${seconds}s`];

  const urgent = left < 60 * 60 * 1000;

  return (
    <>
      {" — "}
      <span
        className={`tnum font-medium ${urgent ? "text-warn" : "text-ink-2"}`}
        title={new Date(until).toLocaleString()}
      >
        {parts.join(" ")} left
      </span>
    </>
  );
}
