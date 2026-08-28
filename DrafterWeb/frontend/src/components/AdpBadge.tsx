import type { AdpProvenance } from "../api";

/**
 * How current the board is.
 *
 * The CSV pipeline discarded this metadata, so a file four months old looked
 * identical to a fresh one. Showing it means you never have to wonder whether
 * you are drafting against stale ADP.
 */
export function AdpBadge({ adp, className = "" }: { adp?: AdpProvenance; className?: string }) {
  if (!adp) return null;

  const drafts = adp.total_drafts?.toLocaleString();
  const detail = drafts ? `${drafts} drafts` : adp.scoring?.toUpperCase();

  if (adp.stale) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-md border border-warn/40 bg-warn-soft px-2 py-1 text-xs text-warn ${className}`}
        title={`The live ADP feed is unreachable. Serving a cached copy from ${adp.fetched_at ?? "an earlier fetch"}.`}
      >
        <Dot className="bg-warn" />
        Cached ADP · {adp.age}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs text-ink-3 ${className}`}
      title={
        adp.sampled_from
          ? `Sampled ${adp.sampled_from} to ${adp.sampled_to}, ${adp.scoring?.toUpperCase()} ${adp.teams}-team`
          : undefined
      }
    >
      <Dot className="bg-accent" />
      ADP {adp.age}
      {detail && <span className="text-ink-3">· {detail}</span>}
    </span>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${className}`} />;
}
