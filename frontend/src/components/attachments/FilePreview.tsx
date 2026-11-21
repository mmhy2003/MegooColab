"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { formatSize } from "@/lib/images";
import { type LoadedText, loadText, type ViewerFile } from "@/lib/preview";

type Status = "loading" | "ready" | "failed" | "gone";

/**
 * The body of the attachment viewer: the open file, shown the way its kind allows. Rendered with key={file.key},
 * so its state starts afresh for each file.
 */
export function FilePreview({
  file,
  zoom,
  onZoom,
  onGone,
}: {
  file: ViewerFile;
  /** The image's zoom, in percent: 100 fits it in the window. */
  zoom: number;
  onZoom: (pct: number) => void;
  /** The server no longer has the file. */
  onGone: () => void;
}) {
  const [status, setStatus] = useState<Status>(file.kind === "none" ? "ready" : "loading");
  const [text, setText] = useState<LoadedText | null>(null);

  // a preview that didn't load: a file the server no longer has, or one the browser can't show
  const fail = () => {
    if (!file.downloadUrl) {
      setStatus("failed");
      return;
    }
    fetch(file.downloadUrl, { headers: { Range: "bytes=0-0" }, credentials: "include" }).then(
      (res) => {
        if (res.status === 404) {
          setStatus("gone");
          onGone();
        } else setStatus("failed");
      },
      () => setStatus("failed"),
    );
  };

  const isText = file.kind === "text";
  useEffect(() => {
    if (!isText) return;
    const ctl = new AbortController();
    loadText(file.src, ctl.signal).then(
      (loaded) => {
        setText(loaded);
        setStatus("ready");
      },
      (err: unknown) => {
        if (ctl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setStatus("gone");
          onGone();
        } else fail();
      },
    );
    return () => ctl.abort();
    // once per file: the component is keyed by it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "gone") return <Card file={file} message="This file is no longer available." download={false} />;
  if (status === "failed") return <Card file={file} message="This file can't be shown here." />;
  if (file.kind === "none" || text?.binary) return <Card file={file} message="No preview for this type of file" />;
  if (file.kind === "pdf" && typeof navigator !== "undefined" && navigator.pdfViewerEnabled === false)
    return (
      <Card file={file} message="This browser can't show PDFs in the page">
        {file.tabUrl && (
          <a href={file.tabUrl} target="_blank" rel="noopener noreferrer" className={BODY_LINK}>
            Open in new tab
          </a>
        )}
      </Card>
    );

  const ready = () => setStatus("ready");
  const fit = zoom === 100;
  return (
    <>
      {file.kind === "image" && (
        <>
          {/* served by MegooColab, after a sign-in check (or a local object URL): next/image would fetch it without
              the session */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={file.src || undefined}
            alt={file.name}
            data-zoom={zoom}
            onLoad={ready}
            onError={fail}
            onClick={() => onZoom(fit ? 200 : 100)}
            style={fit ? undefined : { height: `${zoom}%` }}
            className={`m-auto ${fit ? "max-h-full max-w-full cursor-zoom-in object-contain" : "max-h-none max-w-none cursor-zoom-out"}`}
          />
        </>
      )}
      {file.kind === "pdf" && (
        <iframe title={file.name} src={file.src} onLoad={ready} className="size-full border-0 bg-white" />
      )}
      {file.kind === "text" && text && (
        <div className="m-auto w-full max-w-5xl self-start p-4">
          {text.cut && (
            <p className="mb-3 text-xs text-neutral-400">
              Showing the first 1 MB of {formatSize(file.size)}. Download the file to see all of it.
            </p>
          )}
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-neutral-100">{text.text}</pre>
        </div>
      )}
      {file.kind === "audio" && (
        <audio controls src={file.src} onLoadedMetadata={ready} onError={fail} className="m-auto w-full max-w-xl" />
      )}
      {file.kind === "video" && (
        <video
          controls
          preload="metadata"
          src={file.src}
          onLoadedMetadata={ready}
          onError={fail}
          className="m-auto max-h-full max-w-full"
        />
      )}
      {status === "loading" && (
        <p role="status" className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-neutral-400">
          Loading…
        </p>
      )}
    </>
  );
}

const BODY_LINK =
  "inline-block rounded bg-white/10 px-3 py-1.5 text-sm font-medium text-neutral-100 hover:bg-white/20";

/** A message in place of the file, with the body Download link unless the file is gone. */
function Card({
  file,
  message,
  download = true,
  children,
}: {
  file: ViewerFile;
  message: string;
  download?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="m-auto space-y-3 rounded-lg border border-white/10 bg-white/5 px-6 py-5 text-center">
      <p className="text-sm text-neutral-300">{message}</p>
      {(children || (download && file.downloadUrl)) && (
        <div className="flex justify-center gap-2">
          {children}
          {download && <BodyDownload file={file} />}
        </div>
      )}
    </div>
  );
}

/** The Download link inside the body, for a file the viewer can't show; the top bar has its own. */
function BodyDownload({ file }: { file: ViewerFile }) {
  if (!file.downloadUrl) return null;
  return (
    <a href={file.downloadUrl} aria-label={`Download ${file.name}`} className={BODY_LINK}>
      Download
    </a>
  );
}
