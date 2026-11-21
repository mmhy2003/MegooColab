import { ApiError } from "@/lib/api";
import { type DraftImage, type ImageRef, imageUrl } from "@/lib/images";
import type { Attachment } from "@/lib/types";

export type PreviewKind = "image" | "pdf" | "text" | "audio" | "video" | "none";

/** One file as the viewer shows it. `src` is what the preview loads; `note` is the grey line under the name. */
export type ViewerFile = {
  key: string; name: string; size: number; kind: PreviewKind; src: string;
  downloadUrl?: string; tabUrl?: string; note?: string;
};

const TEXT_EXT = new Set(["txt", "log", "md", "json", "csv", "tsv", "yaml", "yml", "xml", "html", "css", "js", "ts",
  "tsx", "jsx", "py", "go", "rs", "sh", "sql", "toml", "ini", "diff", "patch"]);
const TEXT_TYPES = new Set(["application/json", "application/xml", "application/javascript", "application/x-sh",
  "application/sql", "application/toml", "application/yaml", "application/x-yaml"]);
const ext = (name: string) => /\.([^./]+)$/.exec(name)?.[1].toLowerCase() ?? "";

export function previewKind(contentType: string, filename: string, checkedImage: boolean): PreviewKind {
  const type = contentType.split(";")[0].trim().toLowerCase();
  if (checkedImage || type === "image/svg+xml") return "image";
  if (type === "application/pdf") return "pdf";
  // before the type: browsers report .ts as video (MPEG transport stream)
  if (TEXT_EXT.has(ext(filename))) return "text";
  if (type.startsWith("text/") || TEXT_TYPES.has(type)) return "text";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  return "none";
}

/** The short type label shown instead of a picture: "PDF", "TXT", "MP4"; "FILE" without an extension. */
export const typeChip = (name: string) => ext(name).slice(0, 4).toUpperCase() || "FILE";

// moved here from Attachments.tsx, unchanged
export const SENT_WITH: Record<string, string> = { comment: "comment", agent_message: "message", answer: "answer",
  change_request: "change request", first_message: "first message", nudge: "message" };
export const LINKED = new Set(["comment", "agent_message", "answer"]);

/** "Sara Kim's comment": what the attachment was sent with, or null for a file attached directly. */
export function sentWith(a: Attachment, names?: Map<string, string>): string | null {
  if (!a.message_kind) return null;
  return `${(a.uploaded_by && names?.get(a.uploaded_by)) || "someone"}'s ${SENT_WITH[a.message_kind] ?? "message"}`;
}

export function fromAttachment(a: Attachment, names?: Map<string, string>): ViewerFile {
  const kind = previewKind(a.content_type, a.filename, a.image);
  const inline = a.image || kind === "pdf"; // the two types the server serves inline
  const what = sentWith(a, names);
  return { key: a.id, name: a.filename, size: a.size, kind, src: imageUrl(a.id, inline),
    downloadUrl: imageUrl(a.id, false), tabUrl: inline ? imageUrl(a.id) : undefined,
    note: what ? `from ${what}` : undefined };
}

export const fromImageRef = (img: ImageRef): ViewerFile => ({ key: img.id, name: img.filename, size: img.size,
  kind: "image", src: imageUrl(img.id), downloadUrl: imageUrl(img.id, false), tabUrl: imageUrl(img.id) });

export const fromDraft = (d: DraftImage): ViewerFile => ({ key: d.key, name: d.file.name, size: d.file.size,
  kind: "image", src: d.preview, note: "Not sent yet" });

export const TEXT_LIMIT = 1024 * 1024;
export type LoadedText = { text: string; cut: boolean; binary: boolean };

/** Reads at most the first 1 MB of a file and stops. A NUL byte means it isn't text. Throws ApiError on a non-2xx. */
export async function loadText(url: string, signal?: AbortSignal): Promise<LoadedText> {
  const res = await fetch(url, { credentials: "include", signal });
  if (!res.ok) throw new ApiError(res.status, "load_failed");
  const chunks: Uint8Array[] = [];
  let got = 0;
  let cut = false;
  if (res.body) {
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      if (got > TEXT_LIMIT) {
        cut = true;
        void reader.cancel();
        break;
      }
    }
  } else {
    const all = new Uint8Array(await res.arrayBuffer());
    chunks.push(all);
    got = all.length;
    cut = got > TEXT_LIMIT;
  }
  const bytes = new Uint8Array(Math.min(got, TEXT_LIMIT));
  let at = 0;
  for (const c of chunks) {
    const part = c.subarray(0, bytes.length - at);
    bytes.set(part, at);
    at += part.length;
    if (at >= bytes.length) break;
  }
  if (bytes.includes(0)) return { text: "", cut: false, binary: true };
  return { text: new TextDecoder().decode(bytes), cut, binary: false };
}
