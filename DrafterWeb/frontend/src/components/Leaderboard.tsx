import { useEffect, useState } from "react";
import { ApiError, contracts } from "../api";
import type { Standing } from "../types";

const money = (c: number) => `$${(c / 100).toFixed(2)}`;
const signed = (c: number) =>
  `${c > 0 ? "+" : c < 0 ? "−" : ""}$${(Math.abs(c) / 100).toFixed(2)}`;

/**
 * The season.
 *
 * Ranked on equity -- what you would have if you closed everything now --
 * rather than on cash. Rank on cash and buying anything reads as a loss until
 * it settles, which puts whoever sat out at the top of the table.
 *
 * Everybody appears, traded or not. A table showing eight of twelve looks
 * broken rather than like eight people having been busy.
 */
export function Leaderboard() {
  const [rows, setRows] = useState<Standing[]>([]);
  const [you, setYou] = useState<string | null>(null);
  const [start, setStart] = useState(100_000);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    contracts
      .leaderboard()
      .then((d) => {
        setRows(d.standings);
        setYou(d.you);
        setStart(d.start);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!rows.length) return <p className="text-sm text-ink-3">Nothing yet.</p>;

  const untouched = rows.every((r) => r.markets === 0);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink-3">
        Everyone starts at {money(start)}. Ranked on what you would have if you
        closed every open position now.
      </p>

      {untouched && (
        <p className="text-sm text-ink-3">
          Nobody has traded yet, so it is twelve-way tie.
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-rule bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs tracking-wider text-ink-3 uppercase">
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Manager</th>
              <th className="px-3 py-2 text-right font-medium">Worth</th>
              <th className="px-3 py-2 text-right font-medium">Profit</th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">
                Cash
              </th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">
                Riding
              </th>
              <th className="px-3 py-2 text-right font-medium">Mkts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.user_id}
                className={`border-b border-rule last:border-0 ${
                  r.user_id === you ? "bg-accent-soft" : ""
                }`}
              >
                <td className="tnum px-3 py-2 text-ink-3">{r.rank}</td>
                <td className="px-3 py-2 font-medium">
                  {r.manager}
                  {r.user_id === you && (
                    <span className="ml-1.5 text-xs text-ink-3">you</span>
                  )}
                </td>
                <td className="tnum px-3 py-2 text-right font-semibold">
                  {money(r.equity)}
                </td>
                <td
                  className={`tnum px-3 py-2 text-right ${
                    r.profit > 0
                      ? "text-accent"
                      : r.profit < 0
                        ? "text-danger"
                        : "text-ink-3"
                  }`}
                >
                  {signed(r.profit)}
                </td>
                <td className="tnum hidden px-3 py-2 text-right text-ink-2 sm:table-cell">
                  {money(r.balance)}
                </td>
                <td className="tnum hidden px-3 py-2 text-right text-ink-3 sm:table-cell">
                  {r.staked ? money(r.staked) : "—"}
                </td>
                <td className="tnum px-3 py-2 text-right text-ink-3">
                  {r.markets || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-ink-3">
        <strong>Cash</strong> is what you can spend; <strong>riding</strong> is
        what is tied up in markets that have not settled. Open positions are
        counted at what selling them would fetch, not at the price on the
        board — so buying something cannot make you richer on its own.
      </p>
    </div>
  );
}
