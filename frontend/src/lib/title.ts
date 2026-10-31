"use client";

import { useEffect, useId } from "react";

export const APP_NAME = "MegooColab";

/** The browser tab's title: the page or record first, so a narrow tab still shows it, then the app's name. */
export function pageTitle(...parts: (string | null | undefined)[]): string {
  return [...parts.filter((p): p is string => Boolean(p)), APP_NAME].join(" · ");
}

// Every mounted page and record with its title. A record (a task in the drawer, say) names the tab over the page
// under it, whichever mounted first; among equals the latest wins. Effects run child first, so the order they
// mount in can't decide this alone.
const shown = new Map<string, { title: string; record: boolean; seq: number }>();
let seq = 0;

function apply() {
  let top: { title: string; record: boolean; seq: number } | undefined;
  for (const entry of shown.values()) {
    if (!top || Number(entry.record) > Number(top.record) || (entry.record === top.record && entry.seq > top.seq)) top = entry;
  }
  document.title = top?.title ?? APP_NAME;
}

function useTitle(record: boolean, parts: (string | null | undefined)[]) {
  const id = useId();
  const title = pageTitle(...parts);
  useEffect(() => {
    shown.set(id, { title, record, seq: shown.get(id)?.seq ?? ++seq });
    apply();
  }, [id, title, record]);
  useEffect(
    () => () => {
      shown.delete(id);
      apply();
    },
    [id],
  );
}

/** Names the browser tab after this page while it shows; parts not loaded yet are left out. */
export function usePageTitle(...parts: (string | null | undefined)[]): void {
  useTitle(false, parts);
}

/** Names the tab after a record shown over a page (a task in the drawer), above the page's own title. */
export function useRecordTitle(...parts: (string | null | undefined)[]): void {
  useTitle(true, parts);
}
