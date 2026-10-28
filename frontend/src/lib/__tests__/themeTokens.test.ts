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
    expect(css).toContain("--muted-foreground: #8f84c0;"); // dark
    expect(css).toContain("--color-muted-foreground: var(--muted-foreground)");
    const stale = tsxFiles(SRC).filter((f) => /\btext-muted\b(?!-)/.test(readFileSync(f, "utf8")));
    expect(stale).toEqual([]);
  });
});
