"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { formatSize, type ImageRef, imageUrl } from "@/lib/images";

/** A message's images: thumbnails, up to three across; one opens full size, with the others a step away. */
export function ImageGallery({ images }: { images: ImageRef[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const count = images.length;
  const viewing = open !== null;
  // ← → move through the message's images while one is open
  useEffect(() => {
    if (!viewing) return;
    const onKey = (e: KeyboardEvent) => {
      const by = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (by) setOpen((i) => (i === null ? i : (i + by + count) % count));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [viewing, count]);
  if (count === 0) return null;
  const shown = open === null ? null : images[open];
  const step = (by: number) => setOpen((i) => (i === null ? i : (i + by + count) % count));
  return (
    <>
      <ul className="mt-2 grid max-w-sm grid-cols-3 gap-1.5">
        {images.map((img, i) => (
          <li key={img.id}>
            <button
              type="button"
              aria-label={`Open ${img.filename}`}
              onClick={() => setOpen(i)}
              className="block h-20 w-full cursor-zoom-in overflow-hidden rounded border border-line bg-surface-2 hover:border-cyan"
            >
              {/* served by MegooColab, after a sign-in check: next/image would fetch it without the session */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl(img.id)} alt={img.filename} loading="lazy" className="size-full object-cover" />
            </button>
          </li>
        ))}
      </ul>
      {shown && (
        <Dialog open onClose={() => setOpen(null)} title={shown.filename} wide dismissible>
          <div className="space-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imageUrl(shown.id)} alt={shown.filename} className="mx-auto max-h-[65vh] max-w-full rounded object-contain" />
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              {images.length > 1 && (
                <>
                  <button type="button" aria-label="Previous image" className="icon-btn" onClick={() => step(-1)}>
                    <ChevronLeft size={16} aria-hidden />
                  </button>
                  <span>{open! + 1} of {images.length}</span>
                  <button type="button" aria-label="Next image" className="icon-btn" onClick={() => step(1)}>
                    <ChevronRight size={16} aria-hidden />
                  </button>
                </>
              )}
              <span>{formatSize(shown.size)}</span>
              <a href={imageUrl(shown.id, false)} className="ml-auto text-cyan-ink">
                Download
              </a>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}
