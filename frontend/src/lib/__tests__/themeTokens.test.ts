import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..");
const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : tsxFiles(path);
    return path.endsWith(".tsx") ? [path] : [];
  });
}

describe("theme tokens", () => {
  it("names the muted text colour as shadcn does", () => {
    expect(css).toContain("--muted-foreground: #6b5f99;"); // light
    expect(css).toContain("--muted-foreground: #8e94a3;"); // dark
    expect(css).toContain("--color-muted-foreground: var(--muted-foreground)");
    const stale = tsxFiles(SRC).filter((f) => /\btext-muted\b(?!-)/.test(readFileSync(f, "utf8")));
    expect(stale).toEqual([]);
  });

  it("maps shadcn's colours onto Neon Grid, with the readable cyan as primary", () => {
    for (const line of [
      "--background: var(--bg);",
      "--foreground: var(--fg);",
      "--popover: var(--surface);",
      "--border: var(--line);",
      "--primary: var(--cyan-ink);",
      "--primary-foreground: var(--on-accent);",
      "--ring: var(--cyan);",
      "--destructive: var(--pink);",
      "--muted: var(--surface-2);",
      "--radius: 0.25rem;",
    ]) {
      expect(css).toContain(line);
    }
    expect(css).not.toMatch(/^\s*\.dark\s*\{/m); // dark mode is data-theme, never a .dark class
  });

  it("has four chart colours in each theme", () => {
    const block = (selector: string) => css.slice(css.indexOf(selector), css.indexOf("}", css.indexOf(selector)));
    const light = block(':root[data-theme="light"] {');
    const dark = block(':root[data-theme="dark"] {');
    for (const line of ["--chart-1: #0090a8;", "--chart-2: #d4004f;", "--chart-3: #6d28d9;", "--chart-4: #b7791f;"]) {
      expect(light).toContain(line);
    }
    for (const line of ["--chart-1: #0aa5c0;", "--chart-2: #ff3d81;", "--chart-3: #a06bf0;", "--chart-4: #c98500;"]) {
      expect(dark).toContain(line);
    }
  });
});
