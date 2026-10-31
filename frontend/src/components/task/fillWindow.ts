"use client";

import { useLayoutEffect, type RefObject } from "react";

const MIN_HEIGHT = 384; // 24rem: a very short window still shows a usable task

/** Sizes the element to end at the bottom of the window (less its <main>'s bottom padding), so what it holds scrolls
 * inside it rather than the page. Follows the window's size and anything above it growing or shrinking (a banner). */
export function useFillWindow(ref: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const main = el.closest("main");
    const fit = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      const gap = main ? parseFloat(getComputedStyle(main).paddingBottom) || 0 : 0;
      el.style.height = `${Math.max(MIN_HEIGHT, document.documentElement.clientHeight - top - gap)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    // the page's height changes when something above the element does; the element's own size then stays the same
    const observer = new ResizeObserver(fit);
    observer.observe(document.body);
    return () => {
      window.removeEventListener("resize", fit);
      observer.disconnect();
    };
  }, [ref]);
}
