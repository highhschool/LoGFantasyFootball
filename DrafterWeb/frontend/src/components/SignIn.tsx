import { useEffect, useState } from "react";
import { ApiError, keeper } from "../api";
import type { KeeperManager } from "../types";

/**
 * Proving which of the twelve you are.
 *
 * Sleeper cannot authenticate anyone -- it has no OAuth, and its API answers
 * whoever asks -- so nobody signs in with a password. The league is a closed
 * set of known people and each proves which one with a code sent privately.
 *
 * This started inside the keeper tool, which is where the codes came from, but
 * the identity is not the keeper tool's: contracts needs the same answer, and
 * anything later will too. Sending somebody to a different tool to sign in for
 * this one was the tell that it had outgrown its first home.
 */
export function SignIn({
  onSignedIn,
  heading = "Who are you?",
  blurb = "Find your name and enter the code you were sent.",
  compact = false,
}: {
  onSignedIn: (manager: KeeperManager) => void;
  heading?: string;
  blurb?: string;
  /** Inline inside another screen, rather than owning one. */
  compact?: boolean;
}) {
  const [managers, setManagers] = useState<KeeperManager[]>([]);
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
      const { you } = await keeper.claim(userId, code);
      onSignedIn(you);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={
        compact
          ? "flex flex-col gap-3"
          : "flex flex-col gap-4 rounded-lg border border-rule bg-surface p-5"
      }
    >
      {!compact && (
        <div>
          <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
            {heading}
          </h2>
          <p className="mt-1 text-sm text-ink-3">{blurb}</p>
        </div>
      )}

      <div className={compact ? "flex flex-wrap items-end gap-2" : "contents"}>
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
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-ink-2">Code</span>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter" && userId && code.trim().length >= 4) submit();
            }}
            placeholder="ABC123"
            maxLength={12}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            className="w-full rounded-md border border-rule bg-ground px-3 py-2 tracking-widest"
          />
        </label>

        <button
          type="button"
          disabled={busy || !userId || code.trim().length < 4}
          onClick={submit}
          className={`rounded-md bg-accent px-4 py-2 font-semibold text-ground disabled:opacity-50 ${
            compact ? "" : "self-start"
          }`}
        >
          {busy ? "Checking…" : "Continue"}
        </button>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

/**
 * Who you are, wherever that needs saying, with a way to become somebody else.
 *
 * There is no sign-out: a code claims a manager, and claiming with another
 * code takes it over. That is deliberate -- people switch phones and there is
 * nobody here to appeal to -- so the honest control is "not you?" rather than
 * a door that only locks.
 */
export function Identity({
  manager,
  onChange,
}: {
  manager: KeeperManager | null;
  onChange: () => void;
}) {
  if (!manager) {
    return (
      <button
        type="button"
        onClick={onChange}
        className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold text-ink-2"
      >
        Sign in
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2 text-xs text-ink-3">
      Signed in as{" "}
      <strong className="text-ink-2">
        {manager.display_name || manager.team_name}
      </strong>
      <button
        type="button"
        onClick={onChange}
        className="font-medium text-ink-3 underline underline-offset-2 hover:text-ink"
      >
        not you?
      </button>
    </span>
  );
}
