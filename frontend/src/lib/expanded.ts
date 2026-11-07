"use client";

import { useEffect } from "react";

import { useStoredState } from "@/lib/stored";

/** Something on top that Esc closes first: a dialog, a menu, a list of suggestions. */
const ESC_FIRST = "dialog[open], [role=dialog], [role=menu], [role=listbox]";
// expanding shows only from md up; below it a chat or a task already takes the whole screen
const wide = () => window.matchMedia?.("(min-width: 48rem)").matches ?? true;
const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * Expanded or not (a chat or a task over the whole window), kept in this browser under `key`; Esc collapses, on a
 * wide screen, once nothing else on top wants it. With `keepTyping`, Esc in a text field leaves it expanded too.
 */
export function useExpanded(key: string, { keepTyping = false } = {}): [boolean, (on: boolean) => void] {
  const [expanded, setExpanded] = useStoredState(key, false, "local");
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || !wide() || document.querySelector(ESC_FIRST)) return;
      if (keepTyping && typing(e.target)) return;
      setExpanded(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [expanded, setExpanded, keepTyping]);
  return [expanded, setExpanded];
}
