import { useEffect, useState } from "react";
import { ApiError, players } from "../api";
import type { PlayerProfile as Profile } from "../types";
import { Modal } from "./Modal";
import { PositionBadge } from "./PositionBadge";

/** Column headings, since the API sends the stat keys it stored. */
const HEADING: Record<string, string> = {
  gp: "G", pts_ppr: "PTS",
  pass_cmp: "CMP", pass_att: "ATT", pass_yd: "PYD", pass_td: "PTD",
  pass_int: "INT",
  rush_att: "CAR", rush_yd: "RYD", rush_td: "RTD",
  rec_tgt: "TGT", rec: "REC", rec_yd: "YDS", rec_td: "TD",
  fum_lost: "FUM",
  fgm: "FGM", fga: "FGA", fgm_50p: "50+", xpm: "XPM", xpa: "XPA",
  def_st_td: "TD", int: "INT", ff: "FF", fum_rec: "FR", sack: "SK",
  pts_allow: "PA",
};

const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(1);

/**
 * One player, from every angle the app has one.
 *
 * Four sources and only the first is load-bearing: where he is drafted, then
 * what he has done, who he is, and what is being said about him. The other
 * three fail independently, so each is drawn only when it arrived and its
 * absence is stated rather than left as an empty box.
 */
export function PlayerProfile({
  ffcId,
  atPick,
  onClose,
}: {
  ffcId: number;
  /** Your next pick, if there is one, so survival means something. */
  atPick?: number;
  onClose: () => void;
}) {
  const [data, setData] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    players
      .profile(ffcId, { atPick })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [ffcId, atPick]);

  const title = data ? data.player.name : "Player";

  return (
    <Modal title={title} onClose={onClose}>
      {error && <p className="text-sm text-danger">{error}</p>}
      {!data && !error && <p className="text-sm text-ink-3">Loading…</p>}

      {data && (
        <div className="flex flex-col gap-5">
          <Header data={data} />
          {data.availability && <Availability data={data} />}
          <Draft data={data} />
          {data.have.career ? <Career data={data} /> : <Missing what="career" />}
          {data.have.notes && <Notes data={data} />}
        </div>
      )}
    </Modal>
  );
}

function Header({ data }: { data: Profile }) {
  const { player, bio } = data;
  return (
    <div className="flex items-center gap-4">
      {player.headshot ? (
        <img
          src={player.headshot}
          alt=""
          className="h-16 w-16 shrink-0 rounded-full bg-raised object-cover"
        />
      ) : (
        <PositionBadge position={player.position} />
      )}

      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm text-ink-3">
          <PositionBadge position={player.position} />
          <span>{player.team_full || player.team}</span>
          {player.bye_week && <span>· bye {player.bye_week}</span>}
          {player.rookie && (
            <span className="rounded-full border border-accent px-2 py-0.5 text-[11px] font-semibold text-accent">
              rookie
            </span>
          )}
        </p>
        {bio && (
          <p className="mt-1 text-sm text-ink-3">
            {[
              bio.age && `${bio.age}`,
              bio.college,
              bio.years_exp !== null && `${bio.years_exp} yr${bio.years_exp === 1 ? "" : "s"} pro`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}

      </div>
    </div>
  );
}

/** How loudly a status is drawn. Out is not the same news as questionable. */
const TONE = {
  out: "border-danger/50 bg-danger/10 text-danger",
  doubtful: "border-danger/40 bg-danger/5 text-danger",
  questionable: "border-warn/40 bg-warn-soft text-warn",
  suspended: "border-warn/40 bg-warn-soft text-warn",
  other: "border-rule bg-ground text-ink-2",
} as const;

function Availability({ data }: { data: Profile }) {
  const a = data.availability!;
  return (
    <section className={`rounded-lg border px-4 py-3 ${TONE[a.severity]}`}>
      <p className="text-sm">
        <strong className="font-semibold">{a.status}</strong>
        {" — "}
        {a.phrase}
        {/* A suspension is not an injury, so it does not get a body part
            appended to it as though it were. */}
        {a.injury && a.body_part && <> ({a.body_part.toLowerCase()})</>}
        {a.notes && <>. {a.notes}</>}
      </p>
    </section>
  );
}

function Draft({ data }: { data: Profile }) {
  const a = data.adp;
  return (
    <section className="rounded-lg border border-rule bg-ground p-4">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span>
          <span className="text-xs tracking-wider text-ink-3 uppercase">ADP </span>
          <strong className="tnum text-lg">{a.adp.toFixed(1)}</strong>
          <span className="ml-1 text-sm text-ink-3">({a.round})</span>
        </span>
        <Figure label="Range" value={`${a.high}–${a.low}`} />
        <Figure label="Spread" value={`±${a.stdev.toFixed(1)}`} />
        <Figure label="Drafts" value={a.times_drafted.toLocaleString()} />
      </div>

      {a.survives_to !== null && a.at_pick !== null && (
        <p className="mt-2 text-sm text-ink-2">
          <strong className="tnum">{a.survives_to}%</strong> chance he is still
          there at pick {a.at_pick}.
        </p>
      )}
    </section>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-xs tracking-wider text-ink-3 uppercase">{label} </span>
      <span className="tnum text-sm text-ink-2">{value}</span>
    </span>
  );
}

function Career({ data }: { data: Profile }) {
  const { columns, seasons } = data.career;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold tracking-wider text-ink-3 uppercase">
        Last {seasons.length} season{seasons.length === 1 ? "" : "s"}
      </h3>
      <div className="-mx-1 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-xs text-ink-3">
              <th className="px-2 py-1 text-left font-medium">Year</th>
              {columns.map((c) => (
                <th key={c} className="px-2 py-1 text-right font-medium">
                  {HEADING[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {seasons.map((row) => (
              <tr key={String(row.season)} className="border-b border-rule last:border-0">
                <td className="tnum px-2 py-1 text-ink-2">{row.season}</td>
                {columns.map((c) => (
                  <td key={c} className="tnum px-2 py-1 text-right">
                    {num(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** How much of an analysis piece shows before it needs asking for. */
const PREVIEW = 320;

function Notes({ data }: { data: Profile }) {
  const [open, setOpen] = useState(false);
  const [which, setWhich] = useState(0);

  const note = data.notes[which];
  const long = note.body.length > PREVIEW;
  const body = open || !long ? note.body : `${note.body.slice(0, PREVIEW).trimEnd()}…`;

  return (
    <section className="flex flex-col gap-1">
      <h3 className="flex items-baseline gap-2 text-xs font-semibold tracking-wider text-ink-3 uppercase">
        Latest
        {/* Older pieces are worth reaching, but one at a time -- three
            paragraphs stacked is a wall rather than a profile. */}
        {data.notes.length > 1 && (
          <span className="flex gap-1 normal-case">
            {data.notes.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setWhich(i);
                  setOpen(false);
                }}
                className={`tnum rounded px-1.5 text-[11px] font-semibold ${
                  i === which ? "bg-accent text-ground" : "bg-raised text-ink-3"
                }`}
              >
                {i + 1}
              </button>
            ))}
          </span>
        )}
      </h3>

      <p className="text-sm font-medium">{note.title}</p>

      {note.body && (
        <p className="text-sm whitespace-pre-line text-ink-3">{body}</p>
      )}

      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="self-start text-xs font-semibold text-accent hover:underline"
        >
          {open ? "Show less" : "Read the rest"}
        </button>
      )}

      {note.updated && <p className="text-xs text-ink-3">{note.updated}</p>}
    </section>
  );
}

function Missing({ what }: { what: string }) {
  return (
    <p className="text-sm text-ink-3">
      No {what} on record — nothing since the seasons held, or the feed is
      unavailable.
    </p>
  );
}
