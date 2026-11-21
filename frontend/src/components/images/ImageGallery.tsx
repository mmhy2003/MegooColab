"use client";

import { useMemo, useState } from "react";

import { AttachmentViewer } from "@/components/attachments/AttachmentViewer";
import { type ImageRef, imageUrl } from "@/lib/images";
import { fromImageRef } from "@/lib/preview";

/** A message's images: thumbnails, up to three across; one opens in the full-screen viewer, with the others a step away. */
export function ImageGallery({ images }: { images: ImageRef[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const files = useMemo(() => images.map(fromImageRef), [images]);
  if (images.length === 0) return null;
  return (
    <>
      <ul className="mt-2 grid max-w-sm grid-cols-3 gap-1.5">
        {images.map((img) => (
          <li key={img.id}>
            <button
              type="button"
              aria-label={`Open ${img.filename}`}
              onClick={() => setOpen(img.id)}
              className="block h-20 w-full cursor-zoom-in overflow-hidden rounded border border-line bg-surface-2 hover:border-cyan"
            >
              {/* served by MegooColab, after a sign-in check: next/image would fetch it without the session */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl(img.id)} alt={img.filename} loading="lazy" className="size-full object-cover" />
            </button>
          </li>
        ))}
      </ul>
      <AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />
    </>
  );
}
