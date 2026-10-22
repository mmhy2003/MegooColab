export type ThemePref = "system" | "dark" | "light";

export const THEME_STORAGE_KEY = "megoo-theme";

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    return v === "dark" || v === "light" ? v : "system";
  } catch {
    return "system";
  }
}

export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    // storage unavailable (private mode, blocked): the choice just isn't remembered
  }
}

export function resolveTheme(pref: ThemePref): "dark" | "light" {
  if (pref !== "system") return pref;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(pref: ThemePref): void {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

/** Inline <script> body run before paint so the page never flashes the wrong theme. */
export const themeBootstrapScript = `(function(){try{var p=localStorage.getItem("${THEME_STORAGE_KEY}");}catch(e){}var d=p==="dark"||(p!=="light"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";})();`;
