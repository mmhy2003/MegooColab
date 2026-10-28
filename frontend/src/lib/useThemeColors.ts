"use client";

import { useEffect, useState } from "react";

// chart colour name -> the CSS variable it reads (grey text is --muted-foreground, shadcn's name)
const TOKENS = { "chart-1": "chart-1", "chart-2": "chart-2", muted: "muted-foreground", line: "line", fg: "fg", surface: "surface" } as const;
export type ThemeColors = Record<keyof typeof TOKENS, string>;

function read(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    Object.entries(TOKENS).map(([name, variable]) => [name, style.getPropertyValue(`--${variable}`).trim()]),
  ) as ThemeColors;
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
