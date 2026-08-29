import { Fragment, useEffect, useState } from "react";
import { ApiError, players as playersApi } from "../api";
import type { Player, PlayerProfile as Profile, Position } from "../types";
import { HEADING, num } from "./PlayerProfile";
import { PositionBadge } from "./PositionBadge";

/**
 * Two players of the same position, season by season.
 *
 * It takes the Recommended panel's place while anything is selected and gives
 * it back the moment nothing is, because the two answer the same question from
 * opposite ends -- the advisor picks for you, this lets you settle it yourself.
 *
 * Same position only, and not out of strictness: the stat columns are chosen by
 * position, so a quarterback beside a running back would share almost no column
 * and the table would be two lists standing next to each other.
 */

/** How far back a comparison looks. Enough for a trend, not a career history. */
const SEASONS = 4;

/**
 * What is worth showing per position, in a column narrow enough that the whole
 * career table would need scrolling sideways to read. The full set is still a
 * click away in the player's own profile.
 */
const SHOW: Record<Position, string[]> = {
  QB: ["gp", "pts_ppr", "pass_yd", "pass_td", "pass_int", "rush_yd", "rush_td"],
  RB: ["gp", "pts_ppr", "rush_yd", "rush_td", "rec", "rec_yd", "rec_td"],
  WR: ["gp", "pts_ppr", "rec_tgt", "rec", "rec_yd", "rec_td"],
  TE: ["gp", "pts_ppr", "rec_tgt", "rec", "rec_yd", "rec_td"],
  K: ["gp", "pts_ppr", "fgm", "fga", "xpm"],
  DST: ["gp", "pts_ppr", "sack", "int", "ff", "fum_rec", "def_st_td", "pts_allow"],
};

/** Stats where the smaller number is the better one. */
const LOWER_IS_BETTER = new Set(["pass_int", "fum_lost", "pts_allow"]);

export function ComparePanel({
  picked,
  onRemove,
  onClear,
}: {
  /** One or two players, always of the same position. */
  picked: Player[];
  onRemove: (player: Player) => void;
  onClear: () => void;
}) {
  const [profiles, setProfiles] = useState<Record<number, Profile>>({});
  const [error, setError] = useState<string | null>(null);

  const ids = picked.map((p) => p.ffc_id).join(",");

  useEffect(() => {
    const missing = picked.filter((p) => p.ffc_id && !(p.ffc_id in profiles));
    if (missing.length === 0) return;

    let live = true;
    Promise.all(
      missing.map((p) => playersApi.profile(p.ffc_id, { seasons: SEASONS })),
    )
      .then((fetched) => {
        if (!live) return;
        // Kept by id rather than replaced, so swapping one player out and back
        // does not re-fetch the one that never moved.
        setProfiles((held) => {
          const next = { ...held };
          fetched.forEach((d) => (next[d.player.ffc_id] = d));
          return next;
        });
      })
      .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)));

    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids, profiles]);

  const position = picked[0]?.position;
  const ready = picked.filter((p) => profiles[p.ffc_id]);
  const waiting = ready.length < picked.length;

  return (
    <section className="rounded-lg border border-accent/40 bg-surface">
      <h2 className="flex items-center gap-2 border-b border-rule px-3 py-2">
        <span className="text-xs font-semibold tracking-wider text-ink-3 uppercase">
          Compare
        </span>
        {position && <PositionBadge position={position} />}
        <button
          type="button"
          onClick={onClear}
          className="ml-auto text-[11px] font-semibold text-ink-3 hover:text-ink"
        >
          Clear
        </button>
      </h2>

      <div className="flex divide-x divide-rule border-b border-rule">
        {picked.map((p) => (
          <Who key={p.key} player={p} onRemove={() => onRemove(p)} />
        ))}
        {picked.length === 1 && (
          // The panel is doing nothing useful yet, and saying which position
          // beats leaving somebody hunting for why a checkbox will not tick.
          <p className="flex-1 px-3 py-2 text-xs text-ink-3">
            Tick another {position} to compare.
          </p>
        )}
      </div>

      {error && <p className="px-3 py-3 text-sm text-danger">{error}</p>}

      {!error && waiting && (
        <p className="px-3 py-3 text-sm text-ink-3">Loading seasons…</p>
      )}

      {!error && !waiting && picked.length === 2 && (
        <Seasons picked={picked} profiles={profiles} position={position!} />
      )}
    </section>
  );
}

function Who({ player, onRemove }: { player: Player; onRemove: () => void }) {
  return (
    <div className="flex min-w-0 flex-1 items-start gap-1 px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{player.name}</p>
        <p className="tnum text-[11px] text-ink-3">
          {player.team}
          {player.bye_week !== null && ` · bye ${player.bye_week}`}
          {` · ADP ${player.adp.toFixed(1)}`}
        </p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Stop comparing ${player.name}`}
        title="Remove"
        className="shrink-0 rounded px-1 text-xs text-ink-3 hover:text-ink"
      >
        ✕
      </button>
    </div>
  );
}

function Seasons({
  picked,
  profiles,
  position,
}: {
  picked: Player[];
  profiles: Record<number, Profile>;
  position: Position;
}) {
  const careers = picked.map((p) => profiles[p.ffc_id].career);

  // Only the columns this position is read on, and only those the data
  // actually carries -- a column of dashes says nothing.
  const held = new Set(careers.flatMap((c) => c.columns));
  const columns = (SHOW[position] ?? careers[0].columns).filter((c) => held.has(c));

  // Both players' seasons, newest first. They do not always match: a rookie
  // has one and the man he is being weighed against has four, and the gap is
  // itself worth seeing rather than hiding.
  const seasons = [
    ...new Set(careers.flatMap((c) => c.seasons.map((s) => Number(s.season)))),
  ]
    .sort((a, b) => b - a)
    .slice(0, SEASONS);

  if (seasons.length === 0) {
    return (
      <p className="px-3 py-3 text-sm text-ink-3">
        Neither has a season on record to compare.
      </p>
    );
  }

  const row = (which: number, season: number) =>
    careers[which].seasons.find((s) => Number(s.season) === season);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-rule text-ink-3">
            <th className="px-2 py-1 text-left font-medium"> </th>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1 text-right font-medium">
                {HEADING[c] ?? c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {seasons.map((season) => (
            <Fragment key={season}>
              <tr className="bg-ground">
                <td
                  colSpan={columns.length + 1}
                  className="tnum px-2 py-0.5 text-[10px] font-semibold tracking-wider text-ink-3"
                >
                  {season}
                </td>
              </tr>
              {picked.map((p, i) => {
                const mine = row(i, season);
                const theirs = row(1 - i, season);
                return (
                  <tr key={p.key} className="border-b border-rule last:border-0">
                    <td className="max-w-24 truncate px-2 py-1 text-ink-2">
                      {p.name}
                    </td>
                    {columns.map((c) => (
                      <td
                        key={c}
                        className={`tnum px-2 py-1 text-right ${
                          better(mine?.[c], theirs?.[c], c)
                            ? "font-semibold text-accent"
                            : ""
                        }`}
                      >
                        {mine ? num(mine[c]) : "—"}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Whether this figure is the better of the two, so the eye can find it without
 * reading both rows. A missing season is not a loss -- an injured year would
 * otherwise light the other man up in every column he happened to play.
 */
function better(
  mine: number | null | undefined,
  theirs: number | null | undefined,
  column: string,
): boolean {
  if (mine === null || mine === undefined) return false;
  if (theirs === null || theirs === undefined) return false;
  if (mine === theirs) return false;
  return LOWER_IS_BETTER.has(column) ? mine < theirs : mine > theirs;
}
