/**
 * Which money a slate is played with.
 *
 * The one thing on this screen nobody may misread. Buying five contracts
 * thinking it is league currency when it is the commissioner's actual money is
 * the mistake worth designing against, so the loud treatment goes to the rare
 * case rather than the common one: play money gets a quiet label, real money
 * gets a band across the page saying what happens afterwards.
 */
export function StakesTag({ stakes }: { stakes: "play" | "real" }) {
  const real = stakes === "real";
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${
        real
          ? "bg-danger text-ground"
          : "border border-rule bg-raised text-ink-3"
      }`}
    >
      {real ? "Real money" : "Play money"}
    </span>
  );
}

export function StakesNotice({ stakes }: { stakes: "play" | "real" }) {
  if (stakes !== "real") return null;
  return (
    <p className="rounded-lg border border-danger/50 bg-danger/10 px-4 py-3 text-sm text-danger">
      <strong>This slate is played with real money.</strong> Contracts here are
      not part of your league balance and do not count towards the season
      leaderboard — they settle up with the commissioner afterwards.
    </p>
  );
}
