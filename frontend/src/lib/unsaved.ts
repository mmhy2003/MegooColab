"use client";

import { useEffect } from "react";

import type { AskOptions } from "@/components/ui/ConfirmDialog";

export const DISCARD: AskOptions = {
  tone: "warn",
  title: "Discard your changes?",
  text: "You have unsaved changes here. Leaving now loses them.",
  ok: "Discard",
  cancel: "Keep editing",
};

/**
 * While there are unsaved changes: a click on a link inside MegooColab asks first (the confirm dialog) and, on
 * "Discard", lets the same click through; closing the tab or reloading gets the browser's own warning (browsers allow
 * nothing else there). A link opened in a new tab loses nothing, so it is not asked about.
 */
export function useUnsavedGuard(dirty: boolean, ask: (options: AskOptions) => Promise<boolean>): void {
  useEffect(() => {
    if (!dirty) return;
    let following = false;
    const guardLinks = (e: MouseEvent) => {
      if (following || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      const a = e.target instanceof Element ? (e.target.closest("a[href]") as HTMLAnchorElement | null) : null;
      if (!a || a.target === "_blank" || a.origin !== window.location.origin) return;
      e.preventDefault();
      e.stopPropagation();
      void ask(DISCARD).then((discard) => {
        if (!discard) return;
        following = true;
        a.click(); // the same link, now followed as usual (Next.js handles its own links)
        following = false;
      });
    };
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    document.addEventListener("click", guardLinks, true);
    window.addEventListener("beforeunload", warn);
    return () => {
      document.removeEventListener("click", guardLinks, true);
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty, ask]);
}
