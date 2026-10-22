"use client";

import { useEffect, useState } from "react";

const TOKENS = ["chart-1", "chart-2", "muted", "line", "fg", "surface"] as const;
export type ThemeColors = Record<(typeof TOKENS)[number], string>;

function read(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(TOKENS.map((t) => [t, style.getPropertyValue(`--${t}`).trim()])) as ThemeColors;
}

/** Resolved token colors for SVG chart libraries (which need literal colors), updated on theme change. */
export function useThemeColors(): ThemeColors | null {
  const [colors, setColors] = useState<ThemeColors | null>(null);
  useEffect(() => {
    const update = () => setColors(read());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return colors;
}
