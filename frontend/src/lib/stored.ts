"use client";

import { useCallback, useState } from "react";

type Where = "session" | "local";

function storage(where: Where): Storage {
  return where === "session" ? window.sessionStorage : window.localStorage;
}

/** The stored value, or null when there is none or storage can't be read (a private window, blocked site data). */
export function readStored<T>(key: string, where: Where): T | null {
  try {
    const raw = storage(where).getItem(key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: unknown, where: Where): void {
  try {
    storage(where).setItem(key, JSON.stringify(value));
  } catch {
    // nothing is remembered; the page still works
  }
}

/** State kept for the tab ("session") or the browser ("local"). Read once when the component mounts: pages in the
 *  app render only on the client, after the signed-in user is known, so there is no server render to mismatch. */
export function useStoredState<T>(key: string, initial: T, where: Where): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => readStored<T>(key, where) ?? initial);
  const set = useCallback(
    (next: T) => {
      setValue(next);
      writeStored(key, next, where);
    },
    [key, where],
  );
  return [value, set];
}
