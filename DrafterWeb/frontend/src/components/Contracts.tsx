import { useCallback, useEffect, useState } from "react";
import { ApiError, contracts } from "../api";
import type { ContractBook, ContractMarket, ContractSlate } from "../types";
import { StatusDot, type Phase } from "./StatusDot";

interface Props {
  onBack: () => void;
}

const cents = (n: number) => `${n < 0 ? "-" : ""}$${(Math.abs(n) / 100).toFixed(2)}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "-" : ""}$${(Math.abs(n) / 100).toFixed(2)}`;

/**
 * Contracts.
 *
 * A price is a probability: 30c means the league thinks it is 30% likely, and
 * a contract pays a dollar if it lands. Five a market is the cap, which is
 * what keeps this friendly.
 *
 * Sign-in is the keeper code, so nobody signs up twice.
 */
export function Contracts({ onBack }: Props) {
  const [slates, setSlates] = useState<ContractSlate[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [markets, setMarkets] = useState<ContractMarket[]>([]);
  const [book, setBook] = useState<ContractBook | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (slateId?: string | null) => {
    try {
      const top = await contracts.overview();
      setSlates(top.slates);
      setSignedIn(!!top.you);

      const target = slateId ?? top.slates[0]?.slate_id ?? null;
      setChosen(target);
      if (target) setMarkets((await contracts.slate(target)).markets);
      if (top.you) setBook(await contracts.me().catch(() => null));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const slate = slates.find((s) => s.slate_id === chosen);

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-5 overflow-y-auto p-6">
      <header className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onBack}
          className="self-start text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Tools
        </button>
        <h1 className="text-3xl font-semibold tracking-tight">Contracts</h1>
        <p className="text-sm text-ink-3">
          A price is the league's odds. A contract pays $1 if it lands, and five
          a market is the most anyone can hold.
        </p>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      {signedIn === false && (
        <p className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
          You can watch the board, but trading needs your manager code — sign in
          on the keeper page first.
        </p>
      )}

      {book && <Summary book={book} />}

      {slates.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {slates.map((s) => (
            <button
              key={s.slate_id}
              type="button"
              onClick={() => refresh(s.slate_id)}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                s.slate_id === chosen ? "bg-accent text-ground" : "bg-raised text-ink-2"
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}

      {slate && <Window slate={slate} markets={markets} />}

      <ul className="flex flex-col gap-3">
        {markets.map((m) => (
          <Market
            key={m.market_id}
            market={m}
            canTrade={!!signedIn}
            onTraded={() => refresh(chosen)}
          />
        ))}
      </ul>

      {!markets.length && (
        <p className="text-sm text-ink-3">No markets yet.</p>
      )}
    </div>
  );
}

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        weekday: "short",
        hour: "numeric",
        minute: "2-digit",
      })
    : null;

/**
 * The slate's state, from its markets.
 *
 * Weekly slates close market by market on their own kickoffs, so a slate can
 * be part open and part shut. Any market still taking money makes the slate
 * open, because that is the thing somebody arriving wants to know.
 */
function slatePhase(markets: ContractMarket[]): Phase {
  const phases = new Set(markets.map((m) => m.phase));
  if (phases.has("open")) return "open";
  if (phases.has("pending")) return "pending";
  if (phases.has("closed")) return "closed";
  return "settled";
}

function Window({ slate, markets }: { slate: ContractSlate; markets: ContractMarket[] }) {
  const phase = slatePhase(markets);
  const mixed = new Set(markets.map((m) => m.phase)).size > 1;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-3">
      <StatusDot phase={phase} />
      <span>
        {phase === "pending" && <>&middot; opens {when(slate.opens_at)}</>}
        {phase === "open" && (
          <>
            &middot; until <strong className="text-ink-2">{when(slate.closes_at)}</strong>
            {slate.kind === "draft" && ", when the draft starts"}
            {mixed && " — some markets have closed already"}
          </>
        )}
        {phase === "closed" && <>&middot; markets settle as the draft runs</>}
        {phase === "settled" && <>&middot; everything has settled</>}
      </span>
    </div>
  );
}

function Summary({ book }: { book: ContractBook }) {
  const total = book.realised + book.unrealised;
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 rounded-lg border border-rule bg-surface px-4 py-3 text-sm">
      <span className="font-medium">{book.you.display_name || book.you.team_name}</span>
      <Figure label="Settled" value={book.realised} />
      <Figure label="Open" value={book.unrealised} />
      <span className="ml-auto">
        <span className="text-ink-3">Total </span>
        <strong className={`tnum ${total > 0 ? "text-accent" : total < 0 ? "text-danger" : ""}`}>
          {signed(total)}
        </strong>
      </span>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <span className="text-ink-3">{label} </span>
      <span className={`tnum ${value > 0 ? "text-accent" : value < 0 ? "text-danger" : "text-ink-2"}`}>
        {signed(value)}
      </span>
    </span>
  );
}

function Market({
  market,
  canTrade,
  onTraded,
}: {
  market: ContractMarket;
  canTrade: boolean;
  onTraded: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const held = market.you;
  const side = held?.yes ? "yes" : held?.no ? "no" : null;
  const open = market.phase === "open";
  const room = market.headroom ?? market.cap;

  async function trade(which: "yes" | "no", shares: number) {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const out = await contracts.trade(market.market_id, which, shares);
      const { cash, price_before, price_after } = out.traded;
      setNote(
        shares > 0
          ? `Paid ${cents(cash)} — the line moved ${price_before}¢ to ${price_after}¢.`
          : `Took ${cents(-cash)} back.`,
      );
      onTraded();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-rule bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">{market.question}</p>
        <Outcome market={market} />
      </div>

      <div className="flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
        {/* Per market as well as per slate: in season these close on their own
            kickoffs, so one can be shut while its neighbours still trade. */}
        <StatusDot phase={market.phase} label={market.phase !== "open"} />
        {market.phase === "open" && <span>until {when(market.closes_at)}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Side
          label="Yes"
          price={market.price_yes}
          held={held?.yes ?? 0}
          disabled={!open || !canTrade || busy || room < 1}
          onBuy={() => trade("yes", Math.min(room, 1))}
          onMax={room > 1 ? () => trade("yes", room) : undefined}
        />
        <Side
          label="No"
          price={market.price_no}
          held={held?.no ?? 0}
          disabled={!open || !canTrade || busy || room < 1}
          onBuy={() => trade("no", Math.min(room, 1))}
          onMax={room > 1 ? () => trade("no", room) : undefined}
        />

        {side && open && canTrade && (
          <button
            type="button"
            disabled={busy}
            onClick={() => trade(side, -(held![side] as number))}
            className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold text-ink-2 disabled:opacity-40"
          >
            Sell all
          </button>
        )}
      </div>

      {held && held.yes + held.no > 0 && (
        <p className="text-xs text-ink-3">
          You hold <strong className="text-ink-2">{held.yes || held.no} {held.yes ? "Yes" : "No"}</strong>
          {" · "}paid {cents(held.cash)}
          {market.phase !== "settled" && (
            <>
              {" · "}worth {cents(held.value)}{" "}
              <span className={held.open_pnl >= 0 ? "text-accent" : "text-danger"}>
                ({signed(held.open_pnl)})
              </span>
            </>
          )}
        </p>
      )}

      {note && <p className="text-xs text-ink-2">{note}</p>}
      {problem && <p className="text-xs text-danger">{problem}</p>}
    </li>
  );
}

function Outcome({ market }: { market: ContractMarket }) {
  if (market.resolved === null) {
    return (
      <span className="tnum shrink-0 text-xs text-ink-3">
        {market.traded} traded
      </span>
    );
  }
  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
        market.resolved ? "border-accent text-accent" : "border-rule text-ink-3"
      }`}
    >
      {market.resolved ? "Yes" : "No"}
    </span>
  );
}

function Side({
  label,
  price,
  held,
  disabled,
  onBuy,
  onMax,
}: {
  label: string;
  price: number;
  held: number;
  disabled: boolean;
  onBuy: () => void;
  onMax?: () => void;
}) {
  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={onBuy}
        className={`rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${
          held ? "bg-accent text-ground" : "bg-raised text-ink"
        }`}
      >
        {label} <span className="tnum">{price}&cent;</span>
      </button>
      {onMax && (
        <button
          type="button"
          disabled={disabled}
          onClick={onMax}
          title={`Buy the most you are allowed`}
          className="rounded-md bg-raised px-2 py-1.5 text-[11px] font-semibold text-ink-3 disabled:opacity-40"
        >
          max
        </button>
      )}
    </span>
  );
}
