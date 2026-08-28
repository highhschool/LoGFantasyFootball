import { useCallback, useEffect, useState } from "react";
import { api, ApiError, live, type Health } from "./api";
import { Contracts } from "./components/Contracts";
import { Draft } from "./components/Draft";
import { Home, type Tool } from "./components/Home";
import { Keeper } from "./components/Keeper";
import { LiveDraftView } from "./components/LiveDraftView";
import { LiveSetup } from "./components/LiveSetup";
import { Setup } from "./components/Setup";
import type {
  ConnectDraft,
  DraftSession,
  LiveDraft,
  NewSession,
  SessionSummary,
} from "./types";

/**
 * Four tools behind one door.
 *
 * Each keeps its own sessions, lists and screens; this only decides which one
 * you are looking at.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [booted, setBooted] = useState(false);
  const [tool, setTool] = useState<Tool | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Mock simulator
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<DraftSession | null>(null);
  const [starting, setStarting] = useState(false);

  // Live assistant
  const [liveDrafts, setLiveDrafts] = useState<SessionSummary[]>([]);
  const [liveDraft, setLiveDraft] = useState<LiveDraft | null>(null);
  const [connecting, setConnecting] = useState(false);

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => setSessions([]));
  }, []);

  const refreshLive = useCallback(() => {
    live.list().then(setLiveDrafts).catch(() => setLiveDrafts([]));
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setError(message(e)))
      .finally(() => setBooted(true));
  }, []);

  useEffect(() => {
    if (tool === "mock") refreshSessions();
    if (tool === "live") refreshLive();
  }, [tool, refreshSessions, refreshLive]);

  // ------------------------------------------------------------ mock draft

  async function startMock(body: NewSession) {
    setStarting(true);
    setError(null);
    try {
      setSession(await api.createSession(body));
    } catch (e) {
      setError(message(e));
    } finally {
      setStarting(false);
    }
  }

  async function openMock(id: string) {
    setError(null);
    try {
      setSession(await api.getSession(id));
    } catch (e) {
      setError(message(e));
    }
  }

  async function renameMock(id: string, name: string) {
    await api.updateSession(id, { name }).catch(() => undefined);
    refreshSessions();
  }

  async function deleteMock(id: string) {
    await api.deleteSession(id).catch(() => undefined);
    refreshSessions();
  }

  // -------------------------------------------------------- live assistant

  async function connectLive(body: ConnectDraft) {
    setConnecting(true);
    setError(null);
    try {
      setLiveDraft(await live.connect(body));
    } catch (e) {
      setError(message(e));
    } finally {
      setConnecting(false);
    }
  }

  async function openLive(id: string) {
    setError(null);
    try {
      setLiveDraft(await live.get(id));
    } catch (e) {
      setError(message(e));
    }
  }

  async function renameLive(id: string, name: string) {
    // Renaming is the one thing both tools share a route for.
    await api.updateSession(id, { name }).catch(() => undefined);
    refreshLive();
  }

  async function deleteLive(id: string) {
    await live.remove(id).catch(() => undefined);
    refreshLive();
  }

  // ----------------------------------------------------------------- views

  if (!booted) return <Centered>Loading…</Centered>;

  if (health && health.status !== "ok") {
    return (
      <Centered>
        <strong className="text-danger">Rankings unavailable</strong>
        <p className="mt-2 max-w-sm text-ink-2">
          {health.error ?? "The server could not load any ADP data."}
        </p>
        <p className="mt-2 max-w-sm text-sm text-ink-3">
          The app pulls ADP from Fantasy Football Calculator and caches it. This
          means the feed is unreachable and there is no cached copy yet, so it
          should clear on its own once the connection is back.
        </p>
      </Centered>
    );
  }

  if (session) {
    return (
      <Draft
        session={session}
        onSession={setSession}
        onExit={() => {
          setSession(null);
          refreshSessions();
        }}
        adp={health?.adp}
      />
    );
  }

  if (liveDraft) {
    return (
      <LiveDraftView
        draft={liveDraft}
        onDraft={setLiveDraft}
        onRename={(name) => renameLive(liveDraft.id, name)}
        onExit={() => {
          setLiveDraft(null);
          refreshLive();
        }}
      />
    );
  }

  if (tool === "mock") {
    return (
      <Setup
        sessions={sessions}
        starting={starting}
        error={error}
        adp={health?.adp}
        onStart={startMock}
        onResume={openMock}
        onRename={renameMock}
        onDelete={deleteMock}
        onBack={() => setTool(null)}
      />
    );
  }

  if (tool === "keeper") {
    return <Keeper onBack={() => setTool(null)} />;
  }

  if (tool === "contracts") {
    return <Contracts onBack={() => setTool(null)} />;
  }

  if (tool === "live") {
    return (
      <LiveSetup
        drafts={liveDrafts}
        connecting={connecting}
        error={error}
        adp={health?.adp}
        onConnect={connectLive}
        onOpen={openLive}
        onRename={renameLive}
        onDelete={deleteLive}
        onBack={() => setTool(null)}
      />
    );
  }

  return <Home adp={health?.adp} onPick={setTool} />;
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e);
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6 text-center text-ink-2">
      {children}
    </div>
  );
}
