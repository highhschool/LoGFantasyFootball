import { useEffect, useRef, useState } from "react";

/** Click the name to rename in place; Enter saves, Escape cancels. */
export function SessionTitle({
  name,
  onRename,
}: {
  name: string;
  onRename: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setDraft(name), [name]);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  function commit() {
    const next = draft.trim();
    setEditing(false);
    if (next && next !== name) {
      onRename(next);
    } else {
      setDraft(name);
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
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(name);
            setEditing(false);
          }
        }}
        className="min-w-32 rounded border border-accent bg-ground px-2 py-0.5 text-sm font-semibold"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title="Rename this session"
      className="max-w-52 truncate rounded px-1 text-sm font-semibold hover:bg-raised"
    >
      {name || "Untitled draft"}
    </button>
  );
}
