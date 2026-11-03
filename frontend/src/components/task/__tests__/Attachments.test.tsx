import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Attachments } from "@/components/task/Attachments";
import type { Attachment } from "@/lib/types";

const att = (over: Partial<Attachment>): Attachment => ({
  id: "a1", task_id: "t1", filename: "notes.txt", content_type: "text/plain", size: 11, uploaded_by: "u2",
  created_at: "2026-11-02T10:00:00Z", image: false, message_kind: null, message_id: null, ...over,
});

afterEach(cleanup);

describe("Attachments", () => {
  it("shows a thumbnail for an image, and the comment it came with", () => {
    render(
      <Attachments
        items={[
          att({ id: "i1", filename: "phone.png", content_type: "image/png", image: true, message_kind: "comment", message_id: "c1" }),
          att({}),
        ]}
        names={new Map([["u2", "Sara Kim"]])}
        disabled
        onUpload={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole("img", { name: "phone.png" })).toHaveAttribute("src", "/api/attachments/i1?inline=1");
    expect(screen.getByRole("link", { name: "Sara Kim's comment" })).toHaveAttribute("href", "#activity-c1");
    expect(screen.getAllByRole("img")).toHaveLength(1); // a text file has no thumbnail
  });

  it("names a change request or a first message without a link", () => {
    render(
      <Attachments
        items={[att({ id: "i2", filename: "like.png", image: true, message_kind: "change_request", message_id: "d1" })]}
        names={new Map([["u2", "Sara Kim"]])}
        disabled
        onUpload={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("from Sara Kim's change request")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /change request/ })).toBeNull();
  });
});
