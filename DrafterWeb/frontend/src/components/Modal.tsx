import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * A dialog over whatever you were doing.
 *
 * Rendered through a portal rather than in place. The app's screens are their
 * own scroll containers under a root that hides overflow, and a fixed overlay
 * inside one of those gets clipped by it -- so this goes to the body instead
 * of trying to escape by z-index.
 *
 * Closes on Escape and on the backdrop, and takes focus when it opens so a
 * keyboard is not left behind the dialog. Scrolling is frozen while it is up,
 * which on iOS is the difference between a dialog and a thing floating over a
 * page that slides around underneath it.
 */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);

    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // The first field, so typing starts where it should.
    panel.current?.querySelector<HTMLElement>("select, input, button")?.focus();

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 backdrop-blur-[2px] sm:items-center sm:p-4"
      onMouseDown={(e) => {
        // Only a press that both starts and ends on the backdrop closes it,
        // so a drag that finishes outside the panel does not dismiss the form.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        // Horizontally centred, and sitting a little above the vertical
        // middle. True centre reads as slightly low -- the eye puts the middle
        // of a page above the middle of the pixels -- so the panel carries a
        // bottom margin, which the centring counts as part of it and lifts the
        // visible box by half. On a phone it stays a bottom sheet, where the
        // thumb is, and none of this applies.
        className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-t-2xl border border-rule bg-surface p-5 shadow-xl sm:mb-[14vh] sm:max-h-[78dvh] sm:rounded-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mt-1 -mr-1 rounded-md px-2 py-1 text-xl leading-none text-ink-3 hover:text-ink"
          >
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
