import { X } from "lucide-react";

import { Button } from "@/components/ui/Button";

export type EntryRow = { name: string; value: string; secret: boolean };

const FIELD =
  "min-w-0 rounded border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none disabled:opacity-60";

/** Headers or environment variables: name, value, and whether the value is a secret (set separately, never shown). */
export function EntriesEditor({
  label,
  noun,
  rows,
  onChange,
}: {
  label: string;
  /** "Header" or "Variable": names each field for screen readers */
  noun: string;
  rows: EntryRow[];
  onChange: (rows: EntryRow[]) => void;
}) {
  const set = (i: number, patch: Partial<EntryRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs tracking-wider text-muted-foreground uppercase">{label}</legend>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <input
            aria-label={`${noun} ${i + 1} name`}
            placeholder="NAME"
            value={r.name}
            maxLength={100}
            onChange={(e) => set(i, { name: e.target.value })}
            className={`${FIELD} w-44 font-mono`}
          />
          <input
            aria-label={`${noun} ${i + 1} value`}
            type={r.secret ? "password" : "text"}
            placeholder={r.secret ? "Set below after saving" : "value"}
            disabled={r.secret}
            value={r.secret ? "" : r.value}
            maxLength={2000}
            onChange={(e) => set(i, { value: e.target.value })}
            className={`${FIELD} flex-1 font-mono`}
          />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              aria-label={`${noun} ${i + 1} is secret`}
              checked={r.secret}
              onChange={(e) => set(i, { secret: e.target.checked, value: e.target.checked ? "" : r.value })}
            />
            Secret
          </label>
          <button
            type="button"
            aria-label={`Remove ${noun.toLowerCase()} ${i + 1}`}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="text-muted-foreground hover:text-pink"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      ))}
      <Button variant="ghost" onClick={() => onChange([...rows, { name: "", value: "", secret: false }])}>
        Add {noun.toLowerCase()}
      </Button>
    </fieldset>
  );
}
