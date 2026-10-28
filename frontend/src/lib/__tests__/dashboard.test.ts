import { afterEach, describe, expect, it, vi } from "vitest";

import { readScope, shortDuration, taskLink, writeScope } from "@/lib/dashboard";

afterEach(() => vi.restoreAllMocks());

describe("dashboard helpers", () => {
  it("formats durations", () => {
    expect([shortDuration(42_000), shortDuration(12 * 60_000), shortDuration(5 * 3_600_000), shortDuration(2 * 86_400_000)])
      .toEqual(["42 s", "12 m", "5 h", "2 d"]);
    expect(shortDuration(-5_000)).toBe("0 s");
  });

  it("links a task key to its board", () => expect(taskLink("PAY-12")).toBe("/projects/PAY/board?task=PAY-12"));

  it("remembers the scope, and never offers Everything to a non-admin", () => {
    localStorage.clear();
    expect(readScope(false)).toBe("teams");
    writeScope("mine");
    expect(readScope(false)).toBe("mine");
    writeScope("all");
    expect(readScope(false)).toBe("teams");
    expect(readScope(true)).toBe("all");
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readScope(true)).toBe("teams");
    expect(() => writeScope("mine")).not.toThrow();
  });
});
