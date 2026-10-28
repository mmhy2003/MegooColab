"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";

/** The blurred layer behind an open popup. Portalled to <body>: a parent with its own backdrop blur (the header)
 *  would otherwise confine a fixed layer to its own box. With `onClose`, a click on it or Escape closes the popup. */
export function Backdrop({ onClose, className = "z-20" }: { onClose?: () => void; className?: string }) {
  useEffect(() => {
    if (!onClose) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div data-backdrop aria-hidden className={`fixed inset-0 bg-black/40 backdrop-blur-sm ${className}`} onClick={onClose} />,
    document.body,
  );
}
