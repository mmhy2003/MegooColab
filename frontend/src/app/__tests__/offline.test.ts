import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("offline page", () => {
  it("tries the home page (the dashboard) again", () => {
    const html = readFileSync(join(process.cwd(), "public", "offline.html"), "utf-8");
    expect(html).toContain('<a href="/">Try again</a>');
  });
});
