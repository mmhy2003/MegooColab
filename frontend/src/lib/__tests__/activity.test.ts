import { afterEach, describe, expect, it, vi } from "vitest";

import { countActivityAfter } from "@/lib/activity";

afterEach(() => vi.unstubAllGlobals());

describe("countActivityAfter", () => {
  it("asks how many Activity entries came after one, by its time and id", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ count: 73 }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    expect(await countActivityAfter("PAY-1", "2026-11-12T10:00:00.123456Z", "a49")).toBe(73);
    const url = new URL(String((fetch.mock.calls[0] as unknown[])[0]), "http://x");
    expect(url.pathname).toBe("/api/tasks/PAY-1/activity/count");
    expect(Object.fromEntries(url.searchParams)).toEqual({ after: "2026-11-12T10:00:00.123456Z", after_id: "a49" });
  });
});
