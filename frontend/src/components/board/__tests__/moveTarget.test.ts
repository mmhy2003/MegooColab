import { describe, expect, it } from "vitest";

import { moveTarget } from "@/components/board/moveTarget";

const col = (...keys: string[]) => keys.map((key) => ({ key }));

describe("moveTarget", () => {
  it("dropping at the top puts the card above the first one", () => {
    expect(moveTarget(col("A", "B"), 0, "X")).toEqual({ after_key: "A" });
  });

  it("dropping at the bottom puts the card below the last one", () => {
    expect(moveTarget(col("A", "B"), 2, "X")).toEqual({ before_key: "B" });
  });

  it("dropping in the middle names both neighbours", () => {
    expect(moveTarget(col("A", "B", "C"), 1, "X")).toEqual({ before_key: "A", after_key: "B" });
  });

  it("an empty column needs no neighbours", () => {
    expect(moveTarget([], 0, "X")).toEqual({});
  });

  it("moving down within the same column ignores the card's old slot", () => {
    // [A, B, C, D]: drag A to index 2 → [B, C, A, D]
    expect(moveTarget(col("A", "B", "C", "D"), 2, "A")).toEqual({ before_key: "C", after_key: "D" });
  });

  it("clamps out-of-range indexes", () => {
    expect(moveTarget(col("A"), 9, "X")).toEqual({ before_key: "A" });
    expect(moveTarget(col("A"), -3, "X")).toEqual({ after_key: "A" });
  });
});
