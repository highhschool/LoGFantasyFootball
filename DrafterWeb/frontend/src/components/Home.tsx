import type { AdpProvenance } from "../api";
import { AdpBadge } from "./AdpBadge";

export type Tool = "mock" | "live";

/**
 * Two tools, chosen up front.
 *
 * They are genuinely different jobs -- one invents a draft to practise
 * against, the other watches a real one happening -- so they get separate
 * doors rather than a mode switch buried inside one screen.
 */
export function Home({ adp, onPick }: { adp?: AdpProvenance; onPick: (tool: Tool) => void }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">NGFL Drafter</h1>
        <AdpBadge adp={adp} className="mt-2" />
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card
          title="Mock draft"
          blurb="Practise against eleven bots that draft the way real people do. Set your slot, keepers and a pick clock, then draft, undo, or simulate the rest."
          action="Start a mock"
          onClick={() => onPick("mock")}
        />
        <Card
          title="Live draft assistant"
          blurb="Follow your real Sleeper draft as it happens. Paste the draft link and the board fills itself in — no typing picks while the clock runs."
          action="Follow a draft"
          onClick={() => onPick("live")}
        />
      </div>
    </div>
  );
}

function Card({
  title,
  blurb,
  action,
  onClick,
}: {
  title: string;
  blurb: string;
  action: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-3 rounded-lg border border-rule bg-surface p-5 text-left transition-colors hover:border-accent"
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="flex-1 text-sm text-ink-2">{blurb}</p>
      <span className="text-sm font-semibold text-accent">{action} →</span>
    </button>
  );
}
