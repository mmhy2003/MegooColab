"use client";

import { useEffect, useRef, useState } from "react";

/** A box that may scroll sideways (a wide table, a tab bar, the board) on a narrow screen. It fades the edge that has
 * more, so a phone shows there is more to swipe to. Its scroller carries data-scroll-x: the phone e2e check fails
 * on anything else that scrolls sideways. */
export function ScrollX({
  children,
  className = "",
  innerClassName = "",
  label,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  innerClassName?: string;
  label?: string;
  as?: "div" | "nav";
}) {
  const box = useRef<HTMLElement | null>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const measure = () => {
    const el = box.current;
    if (!el) return;
    const start = el.scrollLeft > 0;
    const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((e) => (e.start === start && e.end === end ? e : { start, end }));
  };
  useEffect(() => {
    measure();
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  return (
    <div className={`relative min-w-0 ${className}`}>
      <Tag
        ref={(el: HTMLElement | null) => {
          box.current = el;
        }}
        data-scroll-x
        aria-label={label}
        onScroll={measure}
        className={`max-w-full min-w-0 overflow-x-auto ${innerClassName}`}
      >
        {children}
      </Tag>
      <span
        aria-hidden
        data-fade="start"
        className={`pointer-events-none absolute inset-y-0 left-0 w-6 bg-linear-to-r from-surface to-transparent ${edges.start ? "" : "hidden"}`}
      />
      <span
        aria-hidden
        data-fade="end"
        className={`pointer-events-none absolute inset-y-0 right-0 w-6 bg-linear-to-l from-surface to-transparent ${edges.end ? "" : "hidden"}`}
      />
    </div>
  );
}
