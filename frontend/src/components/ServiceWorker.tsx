"use client";

import { useEffect } from "react";

/** Registers the service worker (PWA). Production only: in `next dev` it would serve stale builds. */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => undefined); // the app works without it
  }, []);
  return null;
}
