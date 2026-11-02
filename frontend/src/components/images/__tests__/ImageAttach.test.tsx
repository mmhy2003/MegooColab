import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ImageAttach, ImageDropZone } from "@/components/images/ImageAttach";
import { useImageDraft } from "@/lib/images";

const png = (name = "shot.png") => new File(["\x89PNG"], name, { type: "image/png" });

function Box({ disabledReason, onIds }: { disabledReason?: string; onIds?: (ids: string[], uploading: boolean) => void }) {
  const draft = useImageDraft(disabledReason);
  onIds?.(draft.ids, draft.uploading);
  return (
    <ImageDropZone draft={draft}>
      <textarea aria-label="Message" />
      <ImageAttach draft={draft} />
      <button type="submit" disabled={draft.uploading}>Send</button>
    </ImageDropZone>
  );
}

let uploads = 0;
let release: (() => void) | null = null;

beforeEach(() => {
  uploads = 0;
  release = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("/api/images");
      expect(init?.body).toBeInstanceOf(FormData);
      const name = ((init!.body as FormData).get("file") as File).name;
      uploads += 1;
      const n = uploads;
      if (name === "slow.png") await new Promise<void>((r) => (release = r));
      return new Response(JSON.stringify({ id: `img-${n}`, filename: name, size: 4, content_type: "image/png" }), { status: 201 });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]')!;

describe("ImageAttach", () => {
  it("adds through the button and shows a thumbnail with the count", async () => {
    let ids: string[] = [];
    render(<Box onIds={(i) => (ids = i)} />);
    fireEvent.change(fileInput(), { target: { files: [png()] } });
    expect(await screen.findByText("1 of 6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument();
    await waitFor(() => expect(ids).toEqual(["img-1"]));
    expect(fileInput().accept).toBe("image/png,image/jpeg,image/gif,image/webp");
  });

  it("adds a pasted image", async () => {
    render(<Box />);
    fireEvent.paste(screen.getByLabelText("Message"), { clipboardData: { files: [png("image.png")] } });
    expect(await screen.findByRole("button", { name: "Remove image.png" })).toBeInTheDocument();
  });

  it("shows where to drop while dragging, and adds what is dropped", async () => {
    render(<Box />);
    const zone = screen.getByLabelText("Message").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"] } });
    expect(screen.getByText("Drop images to add them")).toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [png("dropped.png")], types: ["Files"] } });
    expect(await screen.findByRole("button", { name: "Remove dropped.png" })).toBeInTheDocument();
    expect(screen.queryByText("Drop images to add them")).toBeNull();
  });

  it("refuses what isn't an image, without uploading it", async () => {
    render(<Box />);
    fireEvent.change(fileInput(), { target: { files: [new File(["%PDF"], "report.pdf", { type: "application/pdf" })] } });
    expect(
      await screen.findByText("report.pdf: only images can be sent (PNG, JPEG, GIF or WebP, up to 5 MB each, 6 per message)."),
    ).toBeInTheDocument();
    expect(uploads).toBe(0);
  });

  it("refuses a seventh image", async () => {
    render(<Box />);
    fireEvent.change(fileInput(), { target: { files: Array.from({ length: 7 }, (_, i) => png(`p${i}.png`)) } });
    expect(await screen.findByText("6 of 6")).toBeInTheDocument();
    expect(screen.getByText(/p6\.png: only images can be sent/)).toBeInTheDocument();
    expect(uploads).toBe(6);
  });

  it("takes one out with its ✕", async () => {
    let ids: string[] = [];
    render(<Box onIds={(i) => (ids = i)} />);
    fireEvent.change(fileInput(), { target: { files: [png("a.png"), png("b.png")] } });
    await waitFor(() => expect(ids).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Remove a.png" }));
    expect(screen.queryByRole("button", { name: "Remove a.png" })).toBeNull();
    expect(ids).toEqual(["img-2"]);
  });

  it("keeps Send off while an upload is in flight", async () => {
    render(<Box />);
    fireEvent.change(fileInput(), { target: { files: [png("slow.png")] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeDisabled());
    await act(async () => release?.());
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  });

  it("is off with the reason when the agent can't be sent images", () => {
    render(<Box disabledReason="Update the runner on laptop-claude's machine to send images." />);
    expect(screen.getByRole("button", { name: "Add images" })).toBeDisabled();
    expect(screen.getByText("Update the runner on laptop-claude's machine to send images.")).toBeInTheDocument();
    fireEvent.paste(screen.getByLabelText("Message"), { clipboardData: { files: [png()] } });
    expect(uploads).toBe(0);
  });
});
