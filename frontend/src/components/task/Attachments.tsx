"use client";

import { Download, Trash2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { AttachmentViewer } from "@/components/attachments/AttachmentViewer";
import { Hint } from "@/components/ui/Hint";
import { formatSize, imageUrl } from "@/lib/images";
import { fromAttachment, LINKED, sentWith, typeChip } from "@/lib/preview";
import type { Attachment } from "@/lib/types";

function SentWith({ a, names }: { a: Attachment; names?: Map<string, string> }) {
  const what = sentWith(a, names);
  if (!what) return null;
  return (
    <small className="block text-[11px] text-muted-foreground">
      from{" "}
      {LINKED.has(a.message_kind ?? "") && a.message_id ? (
        <a href={`#activity-${a.message_id}`} className="text-cyan-ink">
          {what}
        </a>
      ) : (
        what
      )}
    </small>
  );
}

export function Attachments({
  items,
  names,
  disabled,
  onUpload,
  onDelete,
}: {
  items: Attachment[];
  /** who sent the images, by user id */
  names?: Map<string, string>;
  disabled: boolean;
  onUpload: (file: File) => Promise<void>;
  onDelete: (id: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const files = useMemo(() => items.map((a) => fromAttachment(a, names)), [items, names]);
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {items.map((a) => (
          <li key={a.id} className="flex items-center gap-2 text-sm">
            {/* the name is the way in for the keyboard and screen readers; the thumbnail is a larger target */}
            <button
              type="button"
              tabIndex={-1}
              aria-hidden
              onClick={() => setOpen(a.id)}
              className="size-8 shrink-0 overflow-hidden rounded border border-line"
            >
              {a.image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={imageUrl(a.id)} alt="" loading="lazy" className="size-full object-cover" />
              ) : (
                <span className="flex size-full items-center justify-center bg-surface-2 text-[9px] font-bold text-muted-foreground">
                  {typeChip(a.filename)}
                </span>
              )}
            </button>
            <span className="min-w-0 flex-1">
              <button type="button" className="block max-w-full truncate text-left hover:text-cyan-ink" onClick={() => setOpen(a.id)}>
                {a.filename}
              </button>
              <SentWith a={a} names={names} />
            </span>
            <span className="text-xs text-muted-foreground">{formatSize(a.size)}</span>
            <Hint label={`Download ${a.filename}`}>
              <a href={imageUrl(a.id, false)} className="icon-btn h-6 w-6" aria-label={`Download ${a.filename}`}>
                <Download size={12} aria-hidden />
              </a>
            </Hint>
            {!disabled && (
              <Hint label={`Delete ${a.filename}`}>
                <button type="button" className="icon-btn h-6 w-6 hover:text-pink" aria-label={`Delete ${a.filename}`} onClick={() => onDelete(a.id)}>
                  <Trash2 size={12} aria-hidden />
                </button>
              </Hint>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="text-xs text-muted-foreground">No attachments.</li>}
      </ul>
      <AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />
      {!disabled && (
        <>
          <input
            ref={input}
            type="file"
            className="sr-only"
            aria-label="Upload attachment"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) await onUpload(file);
              e.target.value = "";
            }}
          />
          <button type="button" className="text-xs text-cyan-ink" onClick={() => input.current?.click()}>
            + Attach a file (max 25 MB)
          </button>
        </>
      )}
    </div>
  );
}
