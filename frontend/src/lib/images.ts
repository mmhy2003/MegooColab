"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

/** What a message may carry; the server checks the same, by the files' bytes. */
export const ACCEPTED_IMAGES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGES = 6;

export type UploadedImage = { id: string; filename: string; size: number; content_type: string };

/** An image as a message shows it (ActivityItem.images, a round's first-message images). */
export type ImageRef = { id: string; filename: string; size: number };

export const refusalText = (name: string) =>
  `${name}: only images can be sent (PNG, JPEG, GIF or WebP, up to 5 MB each, 6 per message).`;

/** Why the file can't be added, or null. */
export function refusal(file: File): string | null {
  return ACCEPTED_IMAGES.includes(file.type) && file.size <= MAX_IMAGE_BYTES ? null : refusalText(file.name || "image");
}

/** Uploads an image for a message not sent yet: the send links it by its id. */
export function uploadImage(file: File): Promise<UploadedImage> {
  const form = new FormData();
  form.append("file", file);
  return api<UploadedImage>("/api/images", { method: "POST", body: form });
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** The image's own URL: thumbnails show it in the page (inline), the link downloads it. */
export const imageUrl = (id: string, inline = true) => `/api/attachments/${id}${inline ? "?inline=1" : ""}`;

export type DraftImage = { key: string; file: File; preview: string; id?: string };

export type ImageDraft = {
  items: DraftImage[];
  /** the uploaded ones, in the order they were added: what the send carries */
  ids: string[];
  uploading: boolean;
  error: string | null;
  /** set: images can't be added now, and this says why */
  disabledReason?: string;
  add: (files: FileList | File[]) => void;
  remove: (key: string) => void;
  clear: () => void;
};

const preview = (file: File) => (typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : "");
const revoke = (url: string) => {
  if (url && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
};

let next = 0;

/** The images being added to one message: each uploads as soon as it is added. */
export function useImageDraft(disabledReason?: string): ImageDraft {
  const [items, setItems] = useState<DraftImage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(items);
  useEffect(() => {
    live.current = items;
  }, [items]);
  // previews are freed with the box
  useEffect(() => () => live.current.forEach((i) => revoke(i.preview)), []);

  const add = useCallback(
    (files: FileList | File[]) => {
      if (disabledReason) return;
      const refused: string[] = [];
      const taken: DraftImage[] = [];
      let room = MAX_IMAGES - live.current.length;
      for (const file of Array.from(files)) {
        const why = refusal(file) ?? (room <= 0 ? refusalText(file.name || "image") : null);
        if (why) {
          refused.push(why);
          continue;
        }
        room -= 1;
        taken.push({ key: `img-${(next += 1)}`, file, preview: preview(file) });
      }
      setError(refused.length ? refused.join(" ") : null);
      if (!taken.length) return;
      live.current = [...live.current, ...taken];
      setItems(live.current);
      for (const item of taken) {
        uploadImage(item.file).then(
          (up) => setItems((all) => all.map((i) => (i.key === item.key ? { ...i, id: up.id } : i))),
          (err) => {
            revoke(item.preview);
            setItems((all) => all.filter((i) => i.key !== item.key));
            const bad = err instanceof ApiError && ["not_an_image", "image_too_large"].includes(err.detail);
            setError(bad ? refusalText(item.file.name || "image") : errorMessage(err));
          },
        );
      }
    },
    [disabledReason],
  );
  const remove = useCallback((key: string) => {
    const gone = live.current.find((i) => i.key === key);
    // taken back on the server too, so it doesn't count against the unsent images a person may hold
    if (gone?.id) void api(`/api/images/${gone.id}`, { method: "DELETE" }).catch(() => undefined);
    setItems((all) => {
      all.filter((i) => i.key === key).forEach((i) => revoke(i.preview));
      return all.filter((i) => i.key !== key);
    });
  }, []);
  const clear = useCallback(() => {
    setItems((all) => {
      all.forEach((i) => revoke(i.preview));
      return [];
    });
    setError(null);
  }, []);

  return {
    items,
    ids: items.flatMap((i) => (i.id ? [i.id] : [])),
    uploading: items.some((i) => !i.id),
    error,
    disabledReason,
    add,
    remove,
    clear,
  };
}
