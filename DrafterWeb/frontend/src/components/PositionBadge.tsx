import type { Position } from "../types";

const TONE: Record<Position, string> = {
  QB: "bg-qb/15 text-qb",
  RB: "bg-rb/15 text-rb",
  WR: "bg-wr/15 text-wr",
  TE: "bg-te/15 text-te",
  K: "bg-k/15 text-k",
  DST: "bg-dst/15 text-dst",
};

export function PositionBadge({ position, className = "" }: { position: Position; className?: string }) {
  return (
    <span
      className={`inline-flex h-5 min-w-9 items-center justify-center rounded px-1.5 text-[11px] font-semibold tracking-wide ${TONE[position] ?? "bg-raised text-ink-2"} ${className}`}
    >
      {position}
    </span>
  );
}
