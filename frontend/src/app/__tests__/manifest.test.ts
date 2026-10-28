import { describe, expect, it } from "vitest";

import manifest from "@/app/manifest";

describe("web app manifest", () => {
  it("makes MegooColab installable as a standalone app", () => {
    const m = manifest();
    expect(m.name).toBe("MegooColab");
    expect(m.short_name).toBe("MegooColab");
    expect(m.start_url).toBe("/projects");
    expect(m.display).toBe("standalone");
    expect(m.background_color).toBe("#0d0221");
    expect(m.theme_color).toBe("#0d0221");
    const icons = m.icons ?? [];
    expect(icons).toContainEqual({ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" });
    expect(icons).toContainEqual({ src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" });
    expect(icons).toContainEqual({ src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" });
  });
});
