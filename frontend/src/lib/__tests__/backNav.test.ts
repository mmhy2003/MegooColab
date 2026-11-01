import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { areaOf, originFor, recordVisit } from "@/lib/backNav";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("where you came from", () => {
  it("areaOf sorts addresses into reading areas", () => {
    expect(areaOf("/kb/search?q=retry")).toBe("kb-search");
    expect(areaOf("/kb/doc/d1")).toBe("kb-read");
    expect(areaOf("/kb/s1?folder=f1")).toBe("kb-read");
    expect(areaOf("/memory/entity/e1")).toBe("memory-read");
    expect(areaOf("/kb")).toBeNull();
    expect(areaOf("/kb/doc")).toBeNull();
    expect(areaOf("/memory")).toBeNull();
    expect(areaOf("/projects/PAY/board")).toBeNull();
  });

  it("arriving in an area from elsewhere records where you were", () => {
    recordVisit("/projects/PAY/board?task=PAY-12", "PAY-12");
    recordVisit("/kb/doc/d1", "Plan");
    expect(originFor("kb-read")).toEqual({ url: "/projects/PAY/board?task=PAY-12", label: "PAY-12" });
    expect(originFor("memory-read")).toBeNull();
  });

  it("moving inside the area keeps the origin, across spaces too", () => {
    recordVisit("/projects/PAY/board?task=PAY-12", "PAY-12");
    recordVisit("/kb/doc/d1", "Plan");
    recordVisit("/kb/s2?folder=f1", "Guides");
    recordVisit("/kb/doc/d9", "Onboarding");
    expect(originFor("kb-read")).toEqual({ url: "/projects/PAY/board?task=PAY-12", label: "PAY-12" });
  });

  it("coming back to the area from another page resets the origin", () => {
    recordVisit("/projects/PAY/board", "Board");
    recordVisit("/kb/doc/d1", "Plan");
    recordVisit("/kb/search?q=retry", 'results for "retry"');
    recordVisit("/kb/doc/d2", "Design");
    expect(originFor("kb-read")).toEqual({ url: "/kb/search?q=retry", label: 'results for "retry"' });
    expect(originFor("kb-search")).toEqual({ url: "/kb/doc/d1", label: "Plan" });
  });

  it("a label that arrives after the address is kept for the page", () => {
    recordVisit("/teams/t1", null);
    recordVisit("/teams/t1", "Platform");
    recordVisit("/memory/entity/e1", "Payments");
    expect(originFor("memory-read")).toEqual({ url: "/teams/t1", label: "Platform" });
  });

  it("a page whose name never loaded is not an origin", () => {
    recordVisit("/teams/t1", null);
    recordVisit("/memory/entity/e1", "Payments");
    expect(originFor("memory-read")).toBeNull();
  });

  it("works without storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => recordVisit("/projects/PAY/board", "Board")).not.toThrow();
    expect(() => recordVisit("/kb/doc/d1", "Plan")).not.toThrow();
    expect(originFor("kb-read")).toBeNull();
  });
});

describe("a page's name that is still the last page's", () => {
  it("is replaced when the new page says its name is loading", () => {
    recordVisit("/teams/t1", "Platform");
    recordVisit("/teams/t2", "Platform"); // the render that changed the address, with the old trail
    recordVisit("/teams/t2", null); // the new page's own trail, still loading
    recordVisit("/kb/doc/d1", "Plan");
    expect(originFor("kb-read")).toBeNull();
  });
});

describe("going back to an origin", () => {
  it("returning to the origin from the area doesn't make the area its origin", () => {
    recordVisit("/projects/PAY/board", "Board");
    recordVisit("/kb", "Knowledge Base");
    recordVisit("/kb/search?q=retry", 'results for "retry"');
    recordVisit("/kb/doc/d1", "Beta");
    recordVisit("/kb/search?q=retry", 'results for "retry"'); // ← Back to results
    expect(originFor("kb-search")).toEqual({ url: "/kb", label: "Knowledge Base" });
  });

  it("a stored record of another shape is ignored", () => {
    sessionStorage.setItem("megoo.nav", JSON.stringify("junk"));
    expect(() => recordVisit("/projects/PAY/board", "Board")).not.toThrow();
    recordVisit("/kb/doc/d1", "Beta");
    expect(originFor("kb-read")).toEqual({ url: "/projects/PAY/board", label: "Board" });
  });
});
