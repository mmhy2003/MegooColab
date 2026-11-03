"use client";

import { ImagePlus, X } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";

import { ACCEPTED_IMAGES, type ImageDraft, MAX_IMAGES } from "@/lib/images";

/** The message box's Add images button, the images added so far (✕ takes one out) and what was refused. */
/** `compact`: on a phone the button is its icon alone (its name stays "Add images"), to share a row with Send. */
export function ImageAttach({ draft, compact = false }: { draft: ImageDraft; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const n = draft.items.length;
  return (
    <div className="space-y-2">
      {n > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Images to send">
          {draft.items.map((i) => (
            <li key={i.key} className="relative size-14 overflow-hidden rounded border border-line bg-surface-2">
              {/* a local preview of the file being added (an object URL): next/image has nothing to optimise */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {i.preview && <img src={i.preview} alt={i.file.name} className="size-full object-cover" />}
              {!i.id && (
                <span aria-hidden className="absolute inset-x-1 bottom-1 h-[3px] animate-pulse rounded bg-cyan" />
              )}
              <button
                type="button"
                aria-label={`Remove ${i.file.name}`}
                onClick={() => draft.remove(i.key)}
                className="absolute top-0.5 right-0.5 flex size-4 items-center justify-center rounded-full bg-black/70 text-white"
              >
                <X size={10} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <button
          type="button"
          disabled={!!draft.disabledReason || n >= MAX_IMAGES}
          onClick={() => input.current?.click()}
          className={`inline-flex items-center gap-1.5 rounded border border-line px-2 py-1 text-xs text-fg hover:border-cyan disabled:cursor-not-allowed disabled:opacity-50 ${
            compact ? "max-md:size-8 max-md:justify-center max-md:p-0" : ""
          }`}
        >
          <ImagePlus size={14} aria-hidden /> <span className={compact ? "max-md:sr-only" : undefined}>Add images</span>
        </button>
        {n > 0 && <span>{n} of {MAX_IMAGES}</span>}
        {draft.disabledReason && <span>{draft.disabledReason}</span>}
        <input
          ref={input}
          type="file"
          accept={ACCEPTED_IMAGES.join(",")}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) draft.add(Array.from(e.target.files));
            e.target.value = ""; // the same file can be added again after it was taken out
          }}
        />
      </div>
      {draft.error && <p role="alert" className="text-xs text-pink">{draft.error}</p>}
    </div>
  );
}

/** Wraps a message box: images pasted into it or dropped on it are added. */
export function ImageDropZone({ draft, children, className = "" }: { draft: ImageDraft; children: ReactNode; className?: string }) {
  const [over, setOver] = useState(false);
  const takes = !draft.disabledReason;
  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  return (
    <div
      className={`relative ${className}`}
      onPaste={(e) => {
        const files = Array.from(e.clipboardData?.files ?? []);
        if (!takes || !files.length) return;
        e.preventDefault(); // a pasted screenshot is added as an image, not as text
        draft.add(files);
      }}
      onDragEnter={(e) => {
        if (takes && hasFiles(e)) setOver(true);
      }}
      onDragOver={(e) => {
        if (takes && hasFiles(e)) e.preventDefault(); // lets it drop here
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
      }}
      onDrop={(e) => {
        setOver(false);
        if (!takes || !e.dataTransfer?.files?.length) return;
        e.preventDefault();
        draft.add(Array.from(e.dataTransfer.files));
      }}
    >
      {children}
      {over && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded border-2 border-dashed border-cyan bg-cyan/10 text-sm text-cyan-ink">
          Drop images to add them
        </div>
      )}
    </div>
  );
}
