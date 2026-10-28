"use client";

import { Paperclip, Trash2 } from "lucide-react";
import { useRef } from "react";

import type { Attachment } from "@/lib/types";

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function Attachments({
  items,
  disabled,
  onUpload,
  onDelete,
}: {
  items: Attachment[];
  disabled: boolean;
  onUpload: (file: File) => Promise<void>;
  onDelete: (id: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {items.map((a) => (
          <li key={a.id} className="flex items-center gap-2 text-sm">
            <Paperclip size={12} className="text-muted-foreground" aria-hidden />
            <a href={`/api/attachments/${a.id}`} className="min-w-0 flex-1 truncate">{a.filename}</a>
            <span className="text-xs text-muted-foreground">{size(a.size)}</span>
            {!disabled && (
              <button type="button" className="icon-btn h-6 w-6 hover:text-pink" aria-label={`Delete ${a.filename}`} onClick={() => onDelete(a.id)}>
                <Trash2 size={12} aria-hidden />
              </button>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="text-xs text-muted-foreground">No attachments.</li>}
      </ul>
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
