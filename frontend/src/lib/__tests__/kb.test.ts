import { describe, expect, it } from "vitest";

import { folderChain, kbSiblings } from "@/lib/kb";

const doc = (id: string, title: string, folder_id: string | null) => ({ id, title, folder_id, latest_revision: 1, updated_at: "2026-10-20T10:00:00Z" });
const DOCS = [
  doc("b", "Beta", "f1"),
  doc("a", "Alpha", "f1"),
  doc("g", "Gamma", "f1"),
  doc("r", "Readme", null),
  doc("o", "Onboarding", null),
  doc("x", "Elsewhere", "f2"),
];
const FOLDERS = [
  { id: "f1", parent_id: null, name: "Guides" },
  { id: "f2", parent_id: "f1", name: "API" },
  { id: "f3", parent_id: "f2", name: "Webhooks" },
];

describe("kbSiblings", () => {
  it("the documents before and after, in the folder, by title", () => {
    expect(kbSiblings(DOCS, "b")).toEqual({ prev: DOCS[1], next: DOCS[2] });
  });
  it("none before the first, none after the last", () => {
    expect(kbSiblings(DOCS, "a")).toEqual({ prev: null, next: DOCS[0] });
    expect(kbSiblings(DOCS, "g")).toEqual({ prev: DOCS[0], next: null });
  });
  it("a top-level document steps through the other top-level documents", () => {
    expect(kbSiblings(DOCS, "o")).toEqual({ prev: null, next: DOCS[3] });
  });
  it("an unknown document has none", () => {
    expect(kbSiblings(DOCS, "zz")).toEqual({ prev: null, next: null });
  });
});

describe("folderChain", () => {
  it("from the top down to the folder", () => {
    expect(folderChain(FOLDERS, "f3").map((f) => f.name)).toEqual(["Guides", "API", "Webhooks"]);
  });
  it("is empty at the top level and for an unknown folder", () => {
    expect(folderChain(FOLDERS, null)).toEqual([]);
    expect(folderChain(FOLDERS, "nope")).toEqual([]);
  });
});
