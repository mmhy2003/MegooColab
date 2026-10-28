"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { applyTheme, getThemePref, setThemePref, type ThemePref } from "@/lib/theme";
import { Hint } from "@/components/ui/Hint";

const NEXT: Record<ThemePref, ThemePref> = { system: "dark", dark: "light", light: "system" };
const ICON = { system: Monitor, dark: Moon, light: Sun };

export function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(() =>
    typeof window === "undefined" ? "system" : getThemePref(),
  );

  useEffect(() => {
    applyTheme(pref);
    if (pref !== "system") return;
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq?.addEventListener?.("change", onChange);
    return () => mq?.removeEventListener?.("change", onChange);
  }, [pref]);

  const Icon = ICON[pref];
  return (
    <Hint label={`Theme: ${pref} (click to change)`}>
      <button
        type="button"
        className="icon-btn"
        aria-label={`Theme: ${pref}`}
        onClick={() => {
          const next = NEXT[pref];
          setThemePref(next);
          setPref(next);
        }}
      >
        <Icon size={18} aria-hidden />
      </button>
    </Hint>
  );
}
