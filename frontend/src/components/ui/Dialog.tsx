"use client";

import { X } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import { PortalContainerContext } from "@/components/ui/PortalContainer";

export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
  dismissible = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
  /** Close on a click outside the dialog. Off for anything a person types or chooses in, so a stray click loses
   *  nothing; on for dialogs that only show something. */
  dismissible?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // popups opened inside render into the dialog, not under it (see PortalContainer)
  const [element, setElement] = useState<HTMLDialogElement | null>(null);
  // A click on the backdrop lands on the <dialog> itself, outside its box. Count it only when the press started
  // there too: a text selection dragged out of the dialog also ends with a click on the <dialog>.
  const pressedOutside = useRef(false);
  const outside = (e: React.MouseEvent<HTMLDialogElement>) => {
    if (e.target !== e.currentTarget) return false;
    const r = e.currentTarget.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };

  // Mounted only while open. showModal() puts it in the top layer with a ::backdrop and makes the page inert; a
  // <dialog open> attribute would show it non-modal, with neither. (jsdom has no showModal: just show it there.)
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || el.open) return;
    if (el.showModal) el.showModal();
    else el.setAttribute("open", "");
    // showModal() focuses the first button (the close ✕); a field marked data-autofocus takes the focus instead
    el.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    return () => el.close?.();
  }, []);

  if (!open) return null;
  return (
    <dialog
      ref={(el) => {
        ref.current = el;
        setElement(el);
      }}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => {
        pressedOutside.current = outside(e);
      }}
      onClick={(e) => {
        if (dismissible && pressedOutside.current && outside(e)) onClose();
        pressedOutside.current = false;
      }}
      className={`card fixed inset-0 m-auto max-h-[90vh] w-[calc(100%-2rem)] overflow-auto p-0 text-fg backdrop:bg-black/40 backdrop:backdrop-blur-sm ${wide ? "max-w-3xl" : "max-w-md"}`}
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="text-sm font-bold text-cyan-ink glow-cyan">{title}</h2>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
          <X size={16} aria-hidden />
        </button>
      </div>
      <div className="p-4">
        <PortalContainerContext.Provider value={element}>{children}</PortalContainerContext.Provider>
      </div>
    </dialog>
  );
}
