import { describe, expect, it } from "vitest";

import { isNewer, parseVersion, releaseUrl, versionLabel } from "@/lib/versions";

describe("versions", () => {
  it("reads only release versions", () => {
    expect(parseVersion("0.1.0")).toEqual([0, 1, 0]);
    expect(parseVersion("v0.10.2")).toEqual([0, 10, 2]);
    for (const v of ["dev", "0.1.0-dev+abc", "1.0", "", null, undefined]) expect(parseVersion(v)).toBeNull();
  });

  it("compares part by part, as numbers", () => {
    expect(isNewer("0.10.0", "0.9.0")).toBe(true);
    expect(isNewer("0.2.0", "0.1.9")).toBe(true);
    expect(isNewer("0.1.0", "0.1.0")).toBe(false);
    expect(isNewer("0.1.0", "0.2.0")).toBe(false);
  });

  it("never calls a build from source out of date", () => {
    expect(isNewer("0.2.0", "dev")).toBe(false);
    expect(isNewer("0.2.0", "0.1.0-dev+abc")).toBe(false);
    expect(isNewer(null, "0.1.0")).toBe(false);
  });

  it("labels the running version, never with a doubled v", () => {
    expect(versionLabel("0.23.1")).toBe("v0.23.1");
    expect(versionLabel("v0.23.1")).toBe("v0.23.1");
    expect(versionLabel(" dev ")).toBe("dev");
    expect(versionLabel("0.24.0-dev+abc")).toBe("0.24.0-dev+abc");
    for (const v of ["", null, undefined]) expect(versionLabel(v)).toBe("");
  });

  it("links only a release to its notes", () => {
    const url = "https://github.com/mmhy2003/MegooColab/releases/tag/v0.23.1";
    expect(releaseUrl("0.23.1")).toBe(url);
    expect(releaseUrl("v0.23.1")).toBe(url);
    for (const v of ["dev", "0.24.0-dev+abc", "", null]) expect(releaseUrl(v)).toBeNull();
  });
});
