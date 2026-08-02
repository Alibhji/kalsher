import { useState } from "react";

type Props = {
  tags: string[];
  size?: "sm" | "md";
  onRemove?: (tag: string) => void;
};

export function TagList({ tags, size = "sm", onRemove }: Props) {
  if (tags.length === 0) return null;
  const cls = size === "sm" ? "pl-2 pr-1 py-0.5 text-[10px]" : "pl-2.5 pr-1 py-0.5 text-xs";
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span
          key={tag}
          className={`inline-flex items-center gap-0.5 rounded-full bg-violet-950/60 font-medium uppercase tracking-wide text-violet-300 ring-1 ring-violet-800/50 ${cls}`}
        >
          {tag}
          {onRemove ? (
            <button
              type="button"
              aria-label={`Remove tag ${tag}`}
              onClick={() => onRemove(tag)}
              className="rounded-full px-1 text-violet-400/80 hover:bg-violet-900/60 hover:text-violet-100"
            >
              ×
            </button>
          ) : null}
        </span>
      ))}
    </div>
  );
}

export function parseTagInput(value: string): string[] {
  return value
    .split(/[,\s]+/)
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);
}

export function mergeTags(existing: string[], input: string): string[] {
  const seen = new Set(existing);
  const out = [...existing];
  for (const tag of parseTagInput(input)) {
    if (!seen.has(tag)) {
      seen.add(tag);
      out.push(tag);
    }
  }
  return out;
}

type EditorProps = {
  tags: string[];
  onSave: (tags: string[]) => void | Promise<void>;
  saving?: boolean;
  placeholder?: string;
  size?: "sm" | "md";
};

export function TagEditor({ tags, onSave, saving = false, placeholder, size = "sm" }: EditorProps) {
  const inputCls =
    size === "sm"
      ? "mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
      : "mt-1 w-full rounded border border-ink-700 bg-ink-950 px-2 py-1.5 text-sm text-ink-100";

  async function commit(next: string[]) {
    await onSave(next);
  }

  return (
    <TagEditorInner
      tags={tags}
      saving={saving}
      placeholder={placeholder}
      inputCls={inputCls}
      size={size}
      onEnter={(draft, setDraft) => {
        const next = draft.trim() ? mergeTags(tags, draft) : tags;
        setDraft("");
        void commit(next);
      }}
      onRemove={(tag) => void commit(tags.filter((t) => t !== tag))}
    />
  );
}

function TagEditorInner({
  tags,
  saving,
  placeholder,
  inputCls,
  size,
  onEnter,
  onRemove,
}: {
  tags: string[];
  saving: boolean;
  placeholder?: string;
  inputCls: string;
  size: "sm" | "md";
  onEnter: (draft: string, setDraft: (v: string) => void) => void;
  onRemove: (tag: string) => void;
}) {
  const [draft, setDraft] = useState("");

  return (
    <div className="space-y-2">
      <TagList tags={tags} size={size} onRemove={saving ? undefined : onRemove} />
      <input
        type="text"
        value={draft}
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onEnter(draft, setDraft);
          }
        }}
        placeholder={placeholder ?? "Add tag, press Enter to save"}
        className={inputCls}
      />
      {saving ? <p className="text-xs text-ink-500">Saving…</p> : null}
    </div>
  );
}
