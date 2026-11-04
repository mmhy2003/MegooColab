import { describe, expect, it } from "vitest";

import { wordDiff } from "@/lib/wordDiff";

describe("wordDiff", () => {
  it("marks the words that went and came, keeping the spaces", () => {
    expect(wordDiff("a b c", "a x c")).toEqual([
      { op: "same", text: "a " },
      { op: "del", text: "b" },
      { op: "add", text: "x" },
      { op: "same", text: " c" },
    ]);
  });

  it("joins neighbouring words of one kind", () => {
    expect(wordDiff("keep this part", "keep that bit")).toEqual([
      { op: "same", text: "keep " },
      { op: "del", text: "this part" },
      { op: "add", text: "that bit" },
    ]);
  });

  it("gives up on word by word for very long texts", () => {
    const a = Array.from({ length: 300 }, (_, i) => `a${i}`).join(" ");
    const b = Array.from({ length: 300 }, (_, i) => `b${i}`).join(" ");
    expect(wordDiff(a, b)).toEqual([{ op: "del", text: a }, { op: "add", text: b }]);
  });
});
