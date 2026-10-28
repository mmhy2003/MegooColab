import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, proxy } from "@/proxy";

const matches = (path: string) => new RegExp(`^${config.matcher[0]}$`).test(path);

describe("sign-in check", () => {
  it("lets the app files a phone needs before signing in through", () => {
    for (const path of ["/manifest.webmanifest", "/sw.js", "/offline.html"]) expect(matches(path)).toBe(false);
  });

  it("still sends a signed-out visitor of an app page to sign in", () => {
    expect(matches("/projects")).toBe(true);
    expect(proxy(new NextRequest("http://x/projects")).headers.get("location")).toBe("http://x/login?next=%2Fprojects");
  });
});
