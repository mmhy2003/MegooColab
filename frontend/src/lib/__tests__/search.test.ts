import { describe, expect, it } from "vitest";

import { highlight, paramsFromUrl, paramsToUrl, type SearchParams } from "@/lib/search";

describe("highlight", () => {
  it("splits on the markers and ignores stray ones", () => {
    expect(highlight("Retry failed card")).toEqual([
      { text: "Retry ", mark: false },
      { text: "failed", mark: true },
      { text: " card", mark: false },
    ]);
    expect(highlight("no markers")).toEqual([{ text: "no markers", mark: false }]);
    // an unclosed start marker and a stray end marker are dropped, never rendered
    expect(highlight("ab")).toEqual([{ text: "ab", mark: false }]);
    expect(highlight("ab")).toEqual([{ text: "ab", mark: false }]);
    expect(highlight("<img src=x onerror=1> x")).toEqual([
      { text: "<img src=x onerror=1> ", mark: false },
      { text: "x", mark: true },
    ]);
  });
});

describe("search params", () => {
  it("round-trip through the URL", () => {
    const p: SearchParams = {
      q: "payment retry",
      kind: ["task", "document"],
      project: ["11111111-1111-1111-1111-111111111111"],
      status: ["done"],
      assignee: ["user:22222222-2222-2222-2222-222222222222"],
      type: ["bug"],
      label: ['x" OR y', "ops"],
      updated: "30d",
      sort: "newest",
      offset: 40,
      meaning: true,
    };
    const url = paramsToUrl(p);
    expect(paramsFromUrl(new URLSearchParams(url))).toEqual(p);
  });

  it("fills defaults and drops unknown values", () => {
    expect(paramsFromUrl(new URLSearchParams("q=x&sort=weird&offset=-5&updated=1d&meaning=no"))).toEqual({
      q: "x", kind: [], project: [], status: [], assignee: [], type: [], label: [], updated: null,
      sort: "relevance", offset: 0, meaning: false,
    });
    expect(paramsToUrl({ ...paramsFromUrl(new URLSearchParams("q=hi")) })).toBe("q=hi");
  });
});
