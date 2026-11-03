"use client";

import { Paperclip, Trash2 } from "lucide-react";
import { useRef } from "react";

import { Hint } from "@/components/ui/Hint";
import { formatSize, imageUrl } from "@/lib/images";
import type { Attachment } from "@/lib/types";

// what an image was sent with, as the line under it says
const SENT_WITH: Record<string, string> = {
  comment: "comment",
  agent_message: "message",
  answer: "answer",
  change_request: "change request",
  first_message: "first message",
  nudge: "message",
};
// kinds whose message is an Activity item of its own (id = message id): the line links to it
const LINKED = new Set(["comment", "agent_message", "answer"]);

function SentWith({ a, names }: { a: Attachment; names?: Map<string, string> }) {
  if (!a.message_kind) return null;
  const what = `${(a.uploaded_by && names?.get(a.uploaded_by)) || "someone"}'s ${SENT_WITH[a.message_kind] ?? "message"}`;
  return (
    <small className="block text-[11px] text-muted-foreground">
      from{" "}
      {LINKED.has(a.message_kind) && a.message_id ? (
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
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {items.map((a) => (
          <li key={a.id} className="flex items-center gap-2 text-sm">
            {a.image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl(a.id)} alt={a.filename} loading="lazy" className="size-8 shrink-0 rounded border border-line object-cover" />
            ) : (
              <Paperclip size={12} className="text-muted-foreground" aria-hidden />
            )}
            <span className="min-w-0 flex-1">
              <a href={`/api/attachments/${a.id}`} className="block truncate">{a.filename}</a>
              <SentWith a={a} names={names} />
            </span>
            <span className="text-xs text-muted-foreground">{formatSize(a.size)}</span>
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
