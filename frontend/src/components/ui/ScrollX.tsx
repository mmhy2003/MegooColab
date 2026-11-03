"use client";

import { useEffect, useRef, useState } from "react";

type More = "start" | "end" | "both" | null;

// the faded edge: a mask on the scroller, so the fade shows whatever is behind it (a card, the page's grid)
const FADE = "1.5rem";
const MASK: Record<Exclude<More, null>, string> = {
  start: `linear-gradient(to right, transparent 0, black ${FADE})`,
  end: `linear-gradient(to right, black calc(100% - ${FADE}), transparent 100%)`,
  both: `linear-gradient(to right, transparent 0, black ${FADE}, black calc(100% - ${FADE}), transparent 100%)`,
};

/** A box that may scroll sideways (a wide table, a tab bar, the board) on a narrow screen. It fades the edge that has
 * more, so a phone shows there is more to swipe to; `chevron` adds a › there too (tab bars). Its scroller carries
 * data-scroll-x: the phone e2e check fails on anything else that scrolls sideways. */
export function ScrollX({
  children,
  className = "",
  innerClassName = "",
  label,
  as: Tag = "div",
  chevron = false,
}: {
  children: React.ReactNode;
  className?: string;
  innerClassName?: string;
  label?: string;
  as?: "div" | "nav";
  chevron?: boolean;
}) {
  const box = useRef<HTMLElement | null>(null);
  const [more, setMore] = useState<More>(null);
  const measure = () => {
    const el = box.current;
    if (!el) return;
    const start = el.scrollLeft > 0;
    const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setMore(start && end ? "both" : start ? "start" : end ? "end" : null);
  };
  useEffect(() => {
    measure();
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  const mask = more ? MASK[more] : undefined;
  return (
    <div className={`relative min-w-0 ${className}`}>
      <Tag
        ref={(el: HTMLElement | null) => {
          box.current = el;
        }}
        data-scroll-x
        data-more={more ?? undefined}
        aria-label={label}
        onScroll={measure}
        style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
        // relative: positioned content (an sr-only label far along a row) is clipped by the scroller, not the page
        className={`relative max-w-full min-w-0 overflow-x-auto ${innerClassName}`}
      >
        {children}
      </Tag>
      {chevron && (more === "end" || more === "both") && (
        <span aria-hidden data-chevron className="pointer-events-none absolute top-0 right-0 text-sm font-bold text-cyan-ink">
          ›
        </span>
      )}
    </div>
  );
}
