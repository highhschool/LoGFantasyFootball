import { useState } from "react";
import type { Profile } from "../types";

const SIZES = {
  sm: "h-7 w-7 text-[10px]",
  md: "h-10 w-10 text-xs",
  lg: "h-20 w-20 text-lg",
} as const;

/** Two letters from a name, which is what a face falls back to. */
function initials(name: string): string {
  const words = name.trim().split(/[\s_-]+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/**
 * Somebody's face, from whichever source has one.
 *
 * An upload wins, Sleeper's avatar is the fallback, and initials cover the
 * rest -- so the page never shows a broken image or an empty circle. Sleeper's
 * lives on their CDN and can fail on its own, which is why loading it is
 * treated as something that might not work rather than something that will.
 */
export function Avatar({
  profile,
  size = "md",
  className = "",
}: {
  profile: Pick<Profile, "display_name" | "team_name" | "photo" | "avatar_url"> | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [broken, setBroken] = useState(false);

  const name = profile?.display_name || profile?.team_name || "";
  const src = profile?.photo || (broken ? null : profile?.avatar_url);

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-raised font-semibold text-ink-2 ${SIZES[size]} ${className}`}
      title={name || undefined}
    >
      {src ? (
        <img
          src={src}
          alt=""
          onError={() => setBroken(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <span aria-hidden>{initials(name)}</span>
      )}
    </span>
  );
}
