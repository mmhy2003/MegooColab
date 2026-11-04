"use client";

import { KbMarkdown } from "@/components/kb/KbMarkdown";

export const BODY_MAX = 500_000;

/** A document's Markdown body: the text beside its preview, with the length against the limit. */
export function MarkdownField({
  id,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const tooLong = value.length > BODY_MAX;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-xs tracking-wider text-muted-foreground uppercase">
          Body
        </label>
        <textarea
          id={id}
          className="min-h-[24rem] w-full rounded border border-line bg-surface-2 px-3 py-2 font-mono text-sm text-fg focus:border-cyan focus:outline-none"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={tooLong || undefined}
        />
        <p className={`text-xs ${tooLong ? "text-pink" : "text-muted-foreground"}`}>
          {value.length.toLocaleString("en-US")} / {BODY_MAX.toLocaleString("en-US")} characters. Link with [[PAY-12]] or
          [[doc:&lt;id&gt;|Title]].
        </p>
      </div>
      <section aria-label="Preview" className="min-w-0 rounded border border-line p-3">
        <p className="mb-2 text-xs tracking-wider text-muted-foreground uppercase">Preview</p>
        <div className="kb-prose">
          <KbMarkdown>{value}</KbMarkdown>
        </div>
      </section>
    </div>
  );
}
