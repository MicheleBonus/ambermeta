import { useEffect, useState, type ReactNode } from "react";

/** The inspector's one field wrapper, so every label/control pair lines up the same way. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-ink-secondary">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export const CONTROL =
  "w-full px-2 py-1 border border-hairline rounded bg-app text-sm text-ink";

/**
 * A text control that edits a draft and only writes it back on Enter or blur — an
 * every-keystroke mutation would round-trip the whole document per character and fight
 * the cursor. `value` re-seeds the draft whenever the document says something else, so an
 * undo or a change made on the canvas is picked up rather than shadowed by a stale draft.
 */
export function CommitField({
  label,
  value,
  onCommit,
  multiline = false,
  placeholder,
}: {
  label: string;
  value: string;
  onCommit: (next: string) => void;
  multiline?: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  const shared = {
    "aria-label": label,
    value: draft,
    placeholder,
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: commit,
    className: CONTROL,
  };

  return (
    <Field label={label}>
      {multiline ? (
        <textarea {...shared} rows={3} className={`${CONTROL} font-mono`} />
      ) : (
        <input
          {...shared}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") setDraft(value);
          }}
        />
      )}
    </Field>
  );
}
