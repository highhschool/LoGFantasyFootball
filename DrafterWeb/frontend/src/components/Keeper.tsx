import { useCallback, useEffect, useState } from "react";
import { ApiError, keeper } from "../api";
import type { KeeperOption, KeeperState } from "../types";
import { PositionBadge } from "./PositionBadge";

interface Props {
  onBack: () => void;
}

/**
 * Keeper selection.
 *
 * Nobody signs in -- Sleeper cannot authenticate anyone -- so a manager picks
 * their team from the twelve and proves it with a code sent privately. From
 * there they choose from their own roster, already priced.
 */
export function Keeper({ onBack }: Props) {
  const [state, setState] = useState<KeeperState | null>(null);
  const [options, setOptions] = useState<KeeperOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await keeper.status();
      setState(next);
      if (next.you) setOptions(await keeper.roster().then((r) => r.options));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function choose(option: KeeperOption) {
    if (!option.key) return;
    setBusy(true);
    setError(null);
    try {
      await keeper.pick(option.key);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!state) {
    return <Shell onBack={onBack}><p className="text-ink-3">Loading…</p></Shell>;
  }

  if (!state.you) {
    return (
      <Shell onBack={onBack} deadline={state}>
        <Claim onClaimed={refresh} />
      </Shell>
    );
  }

  const chosen = options.find((o) => o.key && o.key === state.pick_key);

  return (
    <Shell onBack={onBack} deadline={state}>
      <p className="text-sm text-ink-2">
        {state.you.display_name || state.you.team_name} —{" "}
        {chosen ? (
          <>
            keeping <strong className="text-ink">{chosen.name}</strong> in round{" "}
            <strong className="text-ink">{chosen.round}</strong>
          </>
        ) : (
          "no keeper chosen yet"
        )}
      </p>

      {error && <p className="text-sm text-danger">{error}</p>}

      {!state.open && (
        <p className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
          The deadline has passed. Selections are locked.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {options.map((option) => (
          <Row
            key={option.sleeper_id}
            option={option}
            selected={!!option.key && option.key === state.pick_key}
            disabled={busy || !state.open || !option.keepable}
            onChoose={() => choose(option)}
          />
        ))}
      </ul>

      <p className="text-xs text-ink-3">
        Keeping a player costs the round his ADP falls in. ADP moves until the
        deadline, so anyone close to a boundary is marked.
      </p>
    </Shell>
  );
}

function Row({
  option,
  selected,
  disabled,
  onChoose,
}: {
  option: KeeperOption;
  selected: boolean;
  disabled: boolean;
  onChoose: () => void;
}) {
  return (
    <li
      className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 ${
        selected ? "border-accent bg-accent-soft" : "border-rule bg-surface"
      }`}
    >
      <PositionBadge position={option.position as never} />

      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{option.name}</div>
        <div className="text-xs text-ink-3">
          {option.team}
          {option.bye_week !== null && ` · bye ${option.bye_week}`}
          {option.adp !== null && ` · ADP ${option.adp.toFixed(1)}`}
        </div>
      </div>

      {option.keepable ? (
        <div className="flex items-center gap-2">
          <span className="text-right">
            <span className="tnum block text-sm font-semibold">
              Round {option.round}
            </span>
            {option.near_boundary && (
              <span className="block text-[11px] text-warn">could slip a round</span>
            )}
          </span>
          <button
            type="button"
            disabled={disabled}
            onClick={onChoose}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${
              selected ? "bg-raised text-ink-2" : "bg-accent text-ground"
            }`}
          >
            {selected ? "Keeping" : "Keep"}
          </button>
        </div>
      ) : (
        <span className="text-xs text-ink-3">not on this year's board</span>
      )}
    </li>
  );
}

function Claim({ onClaimed }: { onClaimed: () => void }) {
  const [managers, setManagers] = useState<{ user_id: string; display_name: string; team_name: string }[]>([]);
  const [userId, setUserId] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    keeper.managers().then(setManagers).catch(() => setManagers([]));
  }, []);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await keeper.claim(userId, code);
      onClaimed();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-rule bg-surface p-5">
      <div>
        <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
          Who are you?
        </h2>
        <p className="mt-1 text-sm text-ink-3">
          Find your name and enter the code you were sent.
        </p>
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-ink-2">Manager</span>
        <select
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="select-field w-full rounded-md border border-rule bg-ground px-3 py-2"
        >
          <option value="">Choose…</option>
          {managers.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.display_name || m.team_name}
              {m.team_name && m.display_name ? ` — ${m.team_name}` : ""}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-ink-2">Code</span>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="ABC123"
          maxLength={12}
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          className="w-full rounded-md border border-rule bg-ground px-3 py-2 tracking-widest"
        />
      </label>

      {error && <p className="text-sm text-danger">{error}</p>}

      <button
        type="button"
        disabled={busy || !userId || code.trim().length < 4}
        onClick={submit}
        className="self-start rounded-md bg-accent px-4 py-2 font-semibold text-ground disabled:opacity-50"
      >
        {busy ? "Checking…" : "Continue"}
      </button>
    </section>
  );
}

function Shell({
  children,
  onBack,
  deadline,
}: {
  children: React.ReactNode;
  onBack: () => void;
  deadline?: KeeperState;
}) {
  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col gap-5 overflow-y-auto p-6">
      <header className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onBack}
          className="self-start text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Tools
        </button>
        <h1 className="text-3xl font-semibold tracking-tight">Keeper selection</h1>
        {deadline?.deadline && (
          <p className="text-sm text-ink-3">
            {deadline.open ? "Closes" : "Closed"}{" "}
            {new Date(deadline.deadline).toLocaleString(undefined, {
              weekday: "long",
              hour: "numeric",
              minute: "2-digit",
            })}
          </p>
        )}
      </header>
      {children}
    </div>
  );
}
