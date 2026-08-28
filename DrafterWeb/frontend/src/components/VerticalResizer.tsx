import { useRef } from "react";

interface Props {
  height: number;
  onHeight: (height: number) => void;
  min: number;
  max: number;
  label?: string;
}

const KEYBOARD_STEP = 24;

/**
 * Drag handle between a panel above and the content below it.
 *
 * Pointer events rather than mouse events, so a trackpad, a touchscreen and a
 * pen all work from one path, and pointer capture keeps the drag alive when
 * the cursor outruns the handle -- which it will, since the handle is a few
 * pixels tall and people drag fast.
 *
 * Exposed as a real separator with arrow-key support, because a resizer that
 * only responds to dragging is unusable without a pointer.
 */
export function VerticalResizer({ height, onHeight, min, max, label = "Resize panel" }: Props) {
  const start = useRef<{ y: number; height: number } | null>(null);

  const clamp = (value: number) => Math.min(max, Math.max(min, value));

  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label={label}
      aria-valuenow={Math.round(height)}
      aria-valuemin={min}
      aria-valuemax={Math.round(max)}
      tabIndex={0}
      onPointerDown={(e) => {
        e.preventDefault();
        start.current = { y: e.clientY, height };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        onHeight(clamp(start.current.height + (e.clientY - start.current.y)));
      }}
      onPointerUp={(e) => {
        start.current = null;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onPointerCancel={() => {
        start.current = null;
      }}
      onDoubleClick={() => onHeight(clamp(Math.round(window.innerHeight * 0.42)))}
      onKeyDown={(e) => {
        if (e.key === "ArrowUp") {
          e.preventDefault();
          onHeight(clamp(height - KEYBOARD_STEP));
        }
        if (e.key === "ArrowDown") {
          e.preventDefault();
          onHeight(clamp(height + KEYBOARD_STEP));
        }
      }}
      title="Drag to resize · double-click to reset"
      className="group -my-1 flex shrink-0 cursor-row-resize items-center justify-center py-1 touch-none"
    >
      <div className="h-1 w-16 rounded-full bg-rule transition-colors group-hover:bg-accent group-focus-visible:bg-accent" />
    </div>
  );
}
