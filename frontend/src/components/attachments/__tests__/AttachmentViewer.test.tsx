import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AttachmentViewer } from "@/components/attachments/AttachmentViewer";
import { fromAttachment, TEXT_LIMIT, type ViewerFile } from "@/lib/preview";
import type { Attachment } from "@/lib/types";

const att = (over: Partial<Attachment>): Attachment => ({
  id: "a1", task_id: "t1", filename: "notes.txt", content_type: "text/plain", size: 11, uploaded_by: "u2",
  created_at: "2026-11-02T10:00:00Z", image: false, message_kind: null, message_id: null, ...over,
});

const files: ViewerFile[] = [
  att({ id: "a", filename: "a.png", content_type: "image/png", image: true, size: 2048 }),
  att({ id: "b", filename: "b.png", content_type: "image/png", image: true, size: 388 * 1024 }),
  att({ id: "t", filename: "notes.txt" }),
  att({ id: "x", filename: "estimate.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
].map((a) => fromAttachment(a));

function Harness({ files, start }: { files: ViewerFile[]; start: string | null }) {
  const [open, setOpen] = useState<string | null>(start);
  return <AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />;
}

afterEach(cleanup);

describe("AttachmentViewer", () => {
  it("opens on the given file with its place, size, download and new-tab links", () => {
    render(<Harness files={files} start="b" />);
    const viewer = screen.getByRole("dialog", { name: "b.png" });
    expect(within(viewer).getByText("2 of 4")).toBeInTheDocument();
    expect(within(viewer).getByText("388.0 KB")).toBeInTheDocument();
    expect(within(viewer).getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/attachments/b");
    const tab = within(viewer).getByRole("link", { name: "Open in new tab" });
    expect(tab).toHaveAttribute("href", "/api/attachments/b?inline=1");
    expect(tab).toHaveAttribute("target", "_blank");
    expect(tab).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("is closed when nothing is open", () => {
    render(<Harness files={files} start={null} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves with the arrows and the arrow keys, wrapping at both ends", () => {
    render(<Harness files={files} start="x" />);
    expect(screen.getByText("4 of 4")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "a.png" })).toBeInTheDocument();
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: "estimate.xlsx" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next file" }));
    expect(screen.getByRole("dialog", { name: "a.png" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous file" }));
    expect(screen.getByRole("dialog", { name: "estimate.xlsx" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous file" }));
    expect(screen.getByRole("dialog", { name: "notes.txt" })).toBeInTheDocument();
  });

  it("leaves the arrow keys to a field typed in", () => {
    render(<Harness files={files} start="a" />);
    const input = document.createElement("input");
    screen.getByRole("dialog").appendChild(input);
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "a.png" })).toBeInTheDocument();
  });

  it("lists the files in a strip that opens them", () => {
    render(<Harness files={files} start="a" />);
    const strip = screen.getByRole("list", { name: "Files" });
    const buttons = within(strip).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Show a.png", "Show b.png", "Show notes.txt", "Show estimate.xlsx",
    ]);
    expect(buttons[0]).toHaveAttribute("aria-current", "true");
    expect(buttons[1]).not.toHaveAttribute("aria-current");
    expect(buttons[0].querySelector("img")).toHaveAttribute("src", "/api/attachments/a?inline=1");
    expect(buttons[2]).toHaveTextContent("TXT");
    expect(buttons[3]).toHaveTextContent("XLSX");
    fireEvent.click(within(strip).getByRole("button", { name: "Show estimate.xlsx" }));
    expect(screen.getByRole("dialog", { name: "estimate.xlsx" })).toBeInTheDocument();
    expect(within(strip).getByRole("button", { name: "Show estimate.xlsx" })).toHaveAttribute("aria-current", "true");
  });

  it("closes on Escape and on Close, and Escape goes no further", () => {
    const outer = vi.fn();
    window.addEventListener("keydown", outer);
    try {
      render(<Harness files={files} start="a" />);
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(outer).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", outer);
    }
    cleanup();
    render(<Harness files={files} start="a" />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("zooms an image in steps, toggles on a click, stops at the ends and resets on the next file", () => {
    render(<Harness files={files} start="a" />);
    const img = () => screen.getByRole("img", { name: "a.png" });
    expect(screen.getByText("100%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("150%")).toBeInTheDocument();
    expect(img()).toHaveAttribute("data-zoom", "150");
    expect(img().style.height).toBe("150%");
    fireEvent.click(img());
    expect(screen.getByText("100%")).toBeInTheDocument();
    fireEvent.click(img());
    expect(screen.getByText("200%")).toBeInTheDocument();
    for (let i = 0; i < 6; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    for (let i = 0; i < 12; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("300%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next file" }));
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "b.png" })).toHaveAttribute("data-zoom", "100");
  });

  it("offers a download for a file it can't show, with no new tab or zoom", () => {
    render(<Harness files={files} start="x" />);
    expect(screen.getByText("No preview for this type of file")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download estimate.xlsx" })).toHaveAttribute("href", "/api/attachments/x");
    expect(screen.queryByRole("link", { name: "Open in new tab" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zoom out" })).toBeNull();
  });

  it("shows one file alone, with no arrows, counter or strip", () => {
    render(<Harness files={[files[0]]} start="a" />);
    expect(screen.getByRole("dialog", { name: "a.png" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next file" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Previous file" })).toBeNull();
    expect(screen.queryByText("1 of 1")).toBeNull();
    expect(screen.queryByRole("list", { name: "Files" })).toBeNull();
  });

  it("closes when the open file leaves the list", () => {
    const { rerender } = render(<Harness files={files} start="b" />);
    expect(screen.getByRole("dialog", { name: "b.png" })).toBeInTheDocument();
    rerender(<Harness files={files.filter((f) => f.key !== "b")} start="b" />);
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(<Harness files={files} start="b" />);
    expect(screen.queryByRole("dialog")).toBeNull(); // closed for good, not just hidden
  });

  it("says it is loading until the image has loaded", () => {
    render(<Harness files={files} start="a" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    fireEvent.load(screen.getByRole("img", { name: "a.png" }));
    expect(screen.queryByRole("status")).toBeNull();
  });
});

const pdf = fromAttachment(att({ id: "p", filename: "r.pdf", content_type: "application/pdf" }));
const text = fromAttachment(att({ id: "a1", filename: "notes.txt" }));
const png = fromAttachment(att({ id: "i", filename: "x.png", content_type: "image/png", image: true }));

describe("FilePreview", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    // jsdom has no pdfViewerEnabled: drop the one a test set
    delete (navigator as { pdfViewerEnabled?: boolean }).pdfViewerEnabled;
  });

  it("shows a PDF in the browser's own viewer", () => {
    render(<Harness files={[pdf]} start="p" />);
    const frame = screen.getByTitle("r.pdf");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("src", "/api/attachments/p?inline=1");
    expect(screen.getByRole("link", { name: "Open in new tab" })).toBeInTheDocument();
  });

  it("offers a new tab and a download when the browser can't show PDFs in the page", () => {
    Object.defineProperty(navigator, "pdfViewerEnabled", { value: false, configurable: true });
    const { container } = render(<Harness files={[pdf]} start="p" />);
    expect(screen.getByText("This browser can't show PDFs in the page")).toBeInTheDocument();
    expect(container.ownerDocument.querySelector("iframe")).toBeNull();
    // the card's own, next to the top bar's (hidden on phones)
    const tabs = screen.getAllByRole("link", { name: "Open in new tab" });
    expect(tabs).toHaveLength(2);
    expect(tabs[1]).toHaveTextContent("Open in new tab");
    expect(tabs[1]).toHaveAttribute("href", "/api/attachments/p?inline=1");
    expect(screen.getByRole("link", { name: "Download r.pdf" })).toHaveAttribute("href", "/api/attachments/p");
  });

  it("shows a text file as plain text", async () => {
    const fetch = vi.fn(async () => new Response("hello"));
    vi.stubGlobal("fetch", fetch);
    render(<Harness files={[text]} start="a1" />);
    const shown = await screen.findByText("hello");
    expect(shown.tagName).toBe("PRE");
    expect(fetch).toHaveBeenCalledWith("/api/attachments/a1", expect.anything());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says when a text file is shown only in part", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("a".repeat(TEXT_LIMIT + 10))));
    const big = { ...text, size: Math.round(3.2 * 1024 * 1024) };
    render(<Harness files={[big]} start="a1" />);
    expect(
      await screen.findByText("Showing the first 1 MB of 3.2 MB. Download the file to see all of it."),
    ).toBeInTheDocument();
  });

  it("has no preview for a text file that turns out not to be text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([104, 0, 105]))));
    render(<Harness files={[text]} start="a1" />);
    expect(await screen.findByText("No preview for this type of file")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download notes.txt" })).toBeInTheDocument();
  });

  it("stops loading a text file when the viewer moves on", () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        signals.push(init.signal!);
        return new Promise<Response>(() => {});
      }),
    );
    render(<Harness files={[text, png]} start="a1" />);
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(false);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "x.png" })).toBeInTheDocument();
    expect(signals[0].aborted).toBe(true);
  });

  it("plays audio and video with the browser's controls", () => {
    const song = fromAttachment(att({ id: "s", filename: "song.mp3", content_type: "audio/mpeg" }));
    const clip = fromAttachment(att({ id: "v", filename: "clip.mp4", content_type: "video/mp4" }));
    render(<Harness files={[song, clip]} start="s" />);
    const audio = document.querySelector("audio");
    expect(audio).toHaveAttribute("controls");
    expect(audio).toHaveAttribute("src", "/api/attachments/s");
    fireEvent.click(screen.getByRole("button", { name: "Next file" }));
    const video = document.querySelector("video");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video).toHaveAttribute("src", "/api/attachments/v");
  });

  it("says a file is gone when the server no longer has it, and offers no download", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetch);
    render(<Harness files={[png]} start="i" />);
    fireEvent.error(screen.getByRole("img", { name: "x.png" }));
    expect(await screen.findByText("This file is no longer available.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/attachments/i",
      expect.objectContaining({ headers: { Range: "bytes=0-0" }, credentials: "include" }),
    );
    expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Download x.png" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says a file can't be shown when the server still has it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 206 })));
    render(<Harness files={[png]} start="i" />);
    fireEvent.error(screen.getByRole("img", { name: "x.png" }));
    expect(await screen.findByText("This file can't be shown here.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download x.png" })).toHaveAttribute("href", "/api/attachments/i");
  });

  it("says an unsent image can't be shown without asking the server", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const draft: ViewerFile = { key: "d", name: "new.png", size: 10, kind: "image", src: "blob:x", note: "Not sent yet" };
    render(<Harness files={[draft]} start="d" />);
    fireEvent.error(screen.getByRole("img", { name: "new.png" }));
    expect(await screen.findByText("This file can't be shown here.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("says a text file is gone when its fetch answers 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 404 })));
    render(<Harness files={[text]} start="a1" />);
    expect(await screen.findByText("This file is no longer available.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Download" })).toBeNull());
  });
});
