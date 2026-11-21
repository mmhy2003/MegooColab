import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { fromAttachment, fromDraft, fromImageRef, loadText, previewKind, TEXT_LIMIT, typeChip } from "@/lib/preview";
import type { Attachment } from "@/lib/types";

const att = (over: Partial<Attachment>): Attachment => ({
  id: "a1", task_id: "t1", filename: "notes.txt", content_type: "text/plain", size: 11, uploaded_by: "u2",
  created_at: "2026-11-02T10:00:00Z", image: false, message_kind: null, message_id: null, ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("previewKind", () => {
  it.each([
    ["image/png", "a.png", true, "image"],
    ["image/svg+xml", "a.svg", false, "image"],
    ["image/png", "fake.png", false, "none"],
    ["application/pdf", "r.pdf", false, "pdf"],
    ["video/mp2t", "main.ts", false, "text"],
    ["text/plain", "notes", false, "text"],
    ["application/json", "data", false, "text"],
    ["text/html; charset=utf-8", "page.html", false, "text"],
    ["application/octet-stream", "build.log", false, "text"],
    ["audio/mpeg", "a.mp3", false, "audio"],
    ["video/mp4", "a.mp4", false, "video"],
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "estimate.xlsx", false, "none"],
    ["application/octet-stream", "blob", false, "none"],
  ])("(%s, %s, %s) is %s", (type, name, checked, kind) => {
    expect(previewKind(type, name, checked)).toBe(kind);
  });
});

describe("typeChip", () => {
  it.each([
    ["report.pdf", "PDF"],
    ["clip.MP4", "MP4"],
    ["archive.tar.gz", "GZ"],
    ["Makefile", "FILE"],
  ])("%s is %s", (name, chip) => {
    expect(typeChip(name)).toBe(chip);
  });
});

describe("fromAttachment", () => {
  it("shows a checked image inline and downloads it plainly", () => {
    const f = fromAttachment(att({ id: "i1", filename: "phone.png", content_type: "image/png", image: true }));
    expect(f).toMatchObject({ key: "i1", name: "phone.png", kind: "image", src: "/api/attachments/i1?inline=1",
      tabUrl: "/api/attachments/i1?inline=1", downloadUrl: "/api/attachments/i1" });
  });

  it("shows a PDF inline and can open it in a tab", () => {
    const f = fromAttachment(att({ id: "p1", filename: "r.pdf", content_type: "application/pdf" }));
    expect(f).toMatchObject({ kind: "pdf", src: "/api/attachments/p1?inline=1", tabUrl: "/api/attachments/p1?inline=1" });
  });

  it("loads a text file plainly and has no tab link", () => {
    const f = fromAttachment(att({}));
    expect(f.kind).toBe("text");
    expect(f.src).toBe("/api/attachments/a1");
    expect(f.tabUrl).toBeUndefined();
  });

  it("says which message the file came with", () => {
    const f = fromAttachment(
      att({ id: "i1", filename: "phone.png", image: true, message_kind: "comment", message_id: "c1" }),
      new Map([["u2", "Sara Kim"]]),
    );
    expect(f.note).toBe("from Sara Kim's comment");
  });

  it("has no note for a file attached directly", () => {
    expect(fromAttachment(att({})).note).toBeUndefined();
  });
});

describe("fromImageRef and fromDraft", () => {
  it("shows a message image inline", () => {
    expect(fromImageRef({ id: "m1", filename: "shot.png", size: 5 })).toEqual({ key: "m1", name: "shot.png", size: 5,
      kind: "image", src: "/api/attachments/m1?inline=1", downloadUrl: "/api/attachments/m1",
      tabUrl: "/api/attachments/m1?inline=1" });
  });

  it("shows an unsent image from its preview, without links", () => {
    const f = fromDraft({ key: "d1", file: new File(["x"], "shot.png", { type: "image/png" }), preview: "blob:1" });
    expect(f).toMatchObject({ key: "d1", name: "shot.png", size: 1, kind: "image", src: "blob:1", note: "Not sent yet" });
    expect(f.downloadUrl).toBeUndefined();
    expect(f.tabUrl).toBeUndefined();
  });
});

describe("loadText", () => {
  const serve = (body: BodyInit, status = 200) => vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status })));

  it("reads a short text", async () => {
    serve("hello\nworld");
    await expect(loadText("/api/attachments/a1")).resolves.toEqual({ text: "hello\nworld", cut: false, binary: false });
  });

  it("stops after the first 1 MB", async () => {
    serve("a".repeat(TEXT_LIMIT + 10));
    const got = await loadText("/api/attachments/a1");
    expect(got.cut).toBe(true);
    expect(got.text.length).toBe(TEXT_LIMIT);
  });

  it("says a file with a NUL byte isn't text", async () => {
    serve(new Uint8Array([104, 105, 0, 1]));
    expect((await loadText("/api/attachments/a1")).binary).toBe(true);
  });

  it("throws an ApiError on a 404", async () => {
    serve("gone", 404);
    const err = await loadText("/api/attachments/a1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
  });
});
