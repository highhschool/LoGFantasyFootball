import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Health } from "./api";
import { Draft } from "./components/Draft";
import { Setup } from "./components/Setup";
import type { DraftSession, NewSession, SessionSummary } from "./types";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<DraftSession | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [booted, setBooted] = useState(false);

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setBooted(true));
    refreshSessions();
  }, [refreshSessions]);

  async function start(body: NewSession) {
    setStarting(true);
    setError(null);
    try {
      setSession(await api.createSession(body));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  async function resume(id: string) {
    setError(null);
    try {
      setSession(await api.getSession(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function remove(id: string) {
    await api.deleteSession(id).catch(() => undefined);
    refreshSessions();
  }

  function exit() {
    setSession(null);
    refreshSessions();
  }

  if (!booted) {
    return <Centered>Loading…</Centered>;
  }

  if (health && health.status !== "ok") {
    return (
      <Centered>
        <strong className="text-danger">Rankings unavailable</strong>
        <p className="mt-2 max-w-sm text-ink-2">
          {health.error ?? "The server could not load a rankings file."} Run{" "}
          <code className="rounded bg-raised px-1">build_rankings.py</code> in
          FantasyDrafterAI, then reload.
        </p>
      </Centered>
    );
  }

  if (session) {
    return <Draft session={session} onSession={setSession} onExit={exit} />;
  }

  return (
    <Setup
      sessions={sessions}
      starting={starting}
      error={error}
      season={health?.season ?? 0}
      playerCount={health?.players_loaded ?? 0}
      onStart={start}
      onResume={resume}
      onDelete={remove}
    />
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6 text-center text-ink-2">
      {children}
    </div>
  );
}
