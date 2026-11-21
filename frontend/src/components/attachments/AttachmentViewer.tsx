"use client";

import { ChevronLeft, ChevronRight, Download, ExternalLink, Minus, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { FilePreview } from "@/components/attachments/FilePreview";
import { Dialog } from "@/components/ui/Dialog";
import { Hint } from "@/components/ui/Hint";
import { formatSize } from "@/lib/images";
import { typeChip, type ViewerFile } from "@/lib/preview";

// always dark, in both themes: literal colours, not the theme's tokens
const BTN =
  "inline-flex size-8 shrink-0 items-center justify-center rounded text-neutral-300 hover:bg-white/10 hover:text-white disabled:opacity-40 disabled:hover:bg-transparent";
const ARROW =
  "absolute top-1/2 z-10 inline-flex size-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-neutral-100 hover:bg-black/80 max-md:top-auto max-md:bottom-20 max-md:translate-y-0";
const MIN_ZOOM = 50;
const MAX_ZOOM = 300;
const ZOOM_STEP = 25;

/**
 * Files shown full screen, one at a time, with the others a step away: arrows, ← →, and a strip along the bottom.
 * The caller keeps which file is open; the viewer closes itself when that file leaves the list.
 */
export function AttachmentViewer({
  files,
  openKey,
  onOpen,
  onClose,
}: {
  files: ViewerFile[];
  /** The open file's key; null: closed. */
  openKey: string | null;
  /** The arrows, the keys and the strip open another file with it. */
  onOpen: (key: string) => void;
  onClose: () => void;
}) {
  const index = openKey === null ? -1 : files.findIndex((f) => f.key === openKey);
  const file = index < 0 ? null : files[index];
  const count = files.length;
  const many = count > 1;
  // the zoom belongs to one file: the next one opens at 100% without an effect resetting it
  const [zoom, setZoom] = useState({ key: "", pct: 100 });
  // the file the server no longer has: its Download goes
  const [gone, setGone] = useState<string | null>(null);

  const lost = openKey !== null && !file;
  useEffect(() => {
    if (lost) onClose();
  }, [lost, onClose]);

  useEffect(() => {
    if (index < 0 || !many) return;
    const onKey = (e: KeyboardEvent) => {
      const by = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!by) return;
      // a player's seek and a field's cursor keep their arrows
      const t = e.target;
      if (t instanceof HTMLMediaElement || t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) return;
      onOpen(files[(index + by + count) % count].key);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, many, count, files, onOpen]);

  if (!file) return null;
  const pct = zoom.key === file.key ? zoom.pct : 100;
  const zoomTo = (p: number) => setZoom({ key: file.key, pct: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, p)) });
  const step = (by: number) => onOpen(files[(index + by + count) % count].key);

  return (
    <Dialog open screen title={file.name} onClose={onClose}>
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-bold">{file.name}</h2>
            {file.note && <p className="text-xs text-neutral-400">{file.note}</p>}
          </div>
          {many && (
            <span className="shrink-0 text-xs text-neutral-400">
              {index + 1} of {count}
            </span>
          )}
          <span className="shrink-0 text-xs text-neutral-400">{formatSize(file.size)}</span>
          {file.kind === "image" && (
            <div className="flex items-center max-md:hidden">
              <Hint label="Zoom out">
                <button type="button" aria-label="Zoom out" className={BTN} disabled={pct <= MIN_ZOOM} onClick={() => zoomTo(pct - ZOOM_STEP)}>
                  <Minus size={16} aria-hidden />
                </button>
              </Hint>
              <span className="w-11 text-center text-xs tabular-nums text-neutral-300">{pct}%</span>
              <Hint label="Zoom in">
                <button type="button" aria-label="Zoom in" className={BTN} disabled={pct >= MAX_ZOOM} onClick={() => zoomTo(pct + ZOOM_STEP)}>
                  <Plus size={16} aria-hidden />
                </button>
              </Hint>
            </div>
          )}
          {file.tabUrl && (
            <Hint label="Open in new tab">
              <a href={file.tabUrl} target="_blank" rel="noopener noreferrer" aria-label="Open in new tab" className={`${BTN} max-md:hidden`}>
                <ExternalLink size={16} aria-hidden />
              </a>
            </Hint>
          )}
          {file.downloadUrl && gone !== file.key && (
            <Hint label="Download">
              <a href={file.downloadUrl} aria-label="Download" className={BTN}>
                <Download size={16} aria-hidden />
              </a>
            </Hint>
          )}
          <Hint label="Close">
            <button type="button" aria-label="Close" className={BTN} onClick={onClose}>
              <X size={16} aria-hidden />
            </button>
          </Hint>
        </div>
        <div className="relative flex min-h-0 flex-1 overflow-auto">
          <FilePreview key={file.key} file={file} zoom={pct} onZoom={zoomTo} onGone={() => setGone(file.key)} />
        </div>
        {many && (
          <>
            <button type="button" aria-label="Previous file" className={`${ARROW} left-3`} onClick={() => step(-1)}>
              <ChevronLeft size={20} aria-hidden />
            </button>
            <button type="button" aria-label="Next file" className={`${ARROW} right-3`} onClick={() => step(1)}>
              <ChevronRight size={20} aria-hidden />
            </button>
            <ul aria-label="Files" className="flex gap-1.5 overflow-x-auto border-t border-white/10 p-2">
              {files.map((f) => (
                <li key={f.key} className="shrink-0">
                  <button
                    type="button"
                    aria-label={`Show ${f.name}`}
                    aria-current={f.key === file.key ? "true" : undefined}
                    onClick={() => onOpen(f.key)}
                    className={`block size-12 overflow-hidden rounded border ${f.key === file.key ? "border-cyan-400" : "border-white/10 opacity-70 hover:opacity-100"}`}
                  >
                    {f.kind === "image" ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={f.src || undefined} alt="" loading="lazy" className="size-full object-cover" />
                    ) : (
                      <span className="flex size-full items-center justify-center bg-white/5 text-[10px] font-bold text-neutral-300">
                        {typeChip(f.name)}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Dialog>
  );
}
