"use client";

import { useState } from "react";

import type { ViewerFile } from "@/lib/preview";

/**
 * The body of the attachment viewer: the open file, shown the way its kind allows. Rendered with key={file.key},
 * so its state starts afresh for each file.
 */
export function FilePreview({
  file,
  zoom,
  onZoom,
}: {
  file: ViewerFile;
  /** The image's zoom, in percent: 100 fits it in the window. */
  zoom: number;
  onZoom: (pct: number) => void;
  /** The server no longer has the file. */
  onGone: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "ready">("loading");
  // PDF, text, audio and video get their own previews in the next step
  if (file.kind !== "image") return <NoPreview file={file} />;
  const fit = zoom === 100;
  return (
    <>
      {/* served by MegooColab, after a sign-in check (or a local object URL): next/image would fetch it without
          the session */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={file.src || undefined}
        alt={file.name}
        data-zoom={zoom}
        onLoad={() => setStatus("ready")}
        onClick={() => onZoom(fit ? 200 : 100)}
        style={fit ? undefined : { height: `${zoom}%` }}
        className={`m-auto ${fit ? "max-h-full max-w-full cursor-zoom-in object-contain" : "max-h-none max-w-none cursor-zoom-out"}`}
      />
      {status === "loading" && (
        <p role="status" className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-neutral-400">
          Loading…
        </p>
      )}
    </>
  );
}

function NoPreview({ file }: { file: ViewerFile }) {
  return (
    <div className="m-auto space-y-3 rounded-lg border border-white/10 bg-white/5 px-6 py-5 text-center">
      <p className="text-sm text-neutral-300">No preview for this type of file</p>
      <BodyDownload file={file} />
    </div>
  );
}

/** The Download link inside the body, for a file the viewer can't show; the top bar has its own. */
function BodyDownload({ file }: { file: ViewerFile }) {
  if (!file.downloadUrl) return null;
  return (
    <a
      href={file.downloadUrl}
      aria-label={`Download ${file.name}`}
      className="inline-block rounded bg-white/10 px-3 py-1.5 text-sm font-medium text-neutral-100 hover:bg-white/20"
    >
      Download
    </a>
  );
}
