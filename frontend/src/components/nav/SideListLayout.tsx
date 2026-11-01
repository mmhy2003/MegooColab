"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";

/** A list beside the content (a Knowledge Base space's tree, Memory's entities). Below md the list is behind a
 *  button that opens it as a panel; picking a link in the panel closes it. */
export function SideListLayout({
  sideLabel,
  side,
  hideSide,
  children,
}: {
  sideLabel: string;
  side: React.ReactNode;
  hideSide?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (hideSide) return <div className="min-w-0">{children}</div>;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
      <aside aria-label={sideLabel} className="card hidden max-h-[calc(100vh-8rem)] self-start overflow-y-auto p-3 md:sticky md:top-16 md:block">
        {side}
      </aside>
      <div className="min-w-0 space-y-4">
        <button type="button" className="rounded border border-line px-2 py-1 text-sm text-fg md:hidden" onClick={() => setOpen(true)}>
          {sideLabel}
        </button>
        {children}
      </div>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-label={sideLabel}>
          <button type="button" aria-hidden tabIndex={-1} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div
            className="relative h-full w-72 max-w-[85vw] overflow-y-auto border-r border-line bg-surface p-3"
            onClickCapture={(e) => {
              if ((e.target as HTMLElement).closest("a")) setOpen(false);
            }}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs tracking-widest text-muted-foreground uppercase">{sideLabel}</span>
              <button type="button" aria-label="Close" className="icon-btn" onClick={() => setOpen(false)}>
                <X size={16} aria-hidden />
              </button>
            </div>
            {side}
          </div>
        </div>
      )}
    </div>
  );
}
