import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  onRename: (name: string) => void;
  /** Where it is the obvious action, a single click; in a list of rows, two. */
  activateOn?: "click" | "dblclick";
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  title?: string;
}

/**
 * A name you can edit in place. Enter commits, Escape reverts, blur commits.
 *
 * Shared by the draft header and the saved-session list so the keyboard
 * behaviour cannot drift between them.
 */
export function InlineName({
  value,
  onRename,
  activateOn = "click",
  className = "",
  inputClassName = "",
  placeholder = "Untitled draft",
  title,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const input = useRef<HTMLInputElement>(null);

  // Someone else may rename it (the draft header and this list show the same
  // session), so follow the prop whenever we are not mid-edit.
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  function commit() {
    const next = draft.trim();
    setEditing(false);
    if (next && next !== value) {
      onRename(next);
    } else {
      setDraft(value);
    }
  }

  if (editing) {
    return (
      <input
        ref={input}
        value={draft}
        maxLength={80}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        className={`rounded border border-accent bg-ground px-2 py-0.5 ${inputClassName}`}
      />
    );
  }

  const activate = () => setEditing(true);

  return (
    <button
      type="button"
      onClick={activateOn === "click" ? activate : undefined}
      onDoubleClick={activateOn === "dblclick" ? activate : undefined}
      title={title ?? (activateOn === "dblclick" ? "Double-click to rename" : "Rename")}
      // Double-click would otherwise select the label text as it opens.
      className={`truncate rounded px-1 text-left select-none hover:bg-raised ${className}`}
    >
      {value || placeholder}
    </button>
  );
}
