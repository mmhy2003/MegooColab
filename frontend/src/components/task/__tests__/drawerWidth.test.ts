import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { clampDrawerWidth, drawerMaxWidth, useDrawerWidth } from "../drawerWidth";

beforeEach(() => localStorage.clear());

describe("clampDrawerWidth", () => {
  it("keeps a width between the narrowest and the window less its margin, in whole pixels", () => {
    expect(clampDrawerWidth(500, 1600)).toBe(720);
    expect(clampDrawerWidth(2000, 1600)).toBe(1552);
    expect(clampDrawerWidth(1000.4, 1600)).toBe(1000);
  });

  it("never goes under the narrowest in a window too small for the range", () => {
    expect(clampDrawerWidth(900, 768)).toBe(720);
    expect(clampDrawerWidth(900, 600)).toBe(720);
    expect(drawerMaxWidth(600)).toBe(720);
  });

  it("falls back to the default width for a width that is not a number", () => {
    expect(clampDrawerWidth(NaN, 1600)).toBe(896);
  });
});

describe("useDrawerWidth", () => {
  it("gives the default width when nothing is stored", () => {
    const { result } = renderHook(() => useDrawerWidth());
    expect(result.current[0]).toBe(896);
  });

  it("gives the stored width", () => {
    localStorage.setItem("tasks.drawerWidth", "1000");
    const { result } = renderHook(() => useDrawerWidth());
    expect(result.current[0]).toBe(1000);
  });

  it("ignores a stored value that is not a number", () => {
    localStorage.setItem("tasks.drawerWidth", '"wide"');
    const { result } = renderHook(() => useDrawerWidth());
    expect(result.current[0]).toBe(896);
  });

  it("keeps a new width in this browser", () => {
    const { result } = renderHook(() => useDrawerWidth());
    act(() => result.current[1](1100));
    expect(result.current[0]).toBe(1100);
    expect(JSON.parse(localStorage.getItem("tasks.drawerWidth")!)).toBe(1100);
  });
});
