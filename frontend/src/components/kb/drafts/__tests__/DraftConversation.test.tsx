import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DraftConversation } from "@/components/kb/drafts/DraftConversation";
import type { KbDraft } from "@/lib/kbDrafts";

function draft(count: number): KbDraft {
  return {
    id: "d1", title: "Deploying payments", body_md: "", open_marks: 0, segments: [],
    messages: Array.from({ length: count }, (_, i) => ({
      id: `m${i}`, author: i % 2 ? "agent" : "person", text: `message ${i}`, target: null,
      created_at: "2026-11-04T10:00:00Z",
    })),
    agent: { id: "a1", name: "laptop-claude", online: true, runner_ok: true },
    space: { id: "s1", kind: "project", name: "Payments" }, folder_id: null, folder_path: "",
    document: null, base_revision: null, state: "idle", last_activity_at: "2026-11-04T10:01:00Z",
  } as unknown as KbDraft;
}

function view(d: KbDraft) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <DraftConversation
        draft={d} target={null} pickAgent={false}
        onClearTarget={() => {}} onSend={async () => true} onStop={() => {}} onAgent={() => {}}
      />
    </QueryClientProvider>
  );
}

// jsdom has no layout: give the message list a height to scroll, and remember where it was scrolled to
const proto = HTMLOListElement.prototype as unknown as Record<string, unknown>;
beforeEach(() => {
  Object.defineProperty(proto, "scrollHeight", { configurable: true, get() { return 100 * (this as HTMLElement).children.length; } });
  Object.defineProperty(proto, "scrollTop", {
    configurable: true,
    get() { return ((this as unknown as Record<string, number>)._top ?? 0); },
    set(v: number) { (this as unknown as Record<string, number>)._top = v; },
  });
});
afterEach(() => {
  cleanup();
  delete proto.scrollHeight;
  delete proto.scrollTop;
});

describe("DraftConversation", () => {
  it("opens at the newest message, and follows the ones that arrive", () => {
    const { rerender } = render(view(draft(6)));
    const list = screen.getByRole("list", { name: "Conversation" });
    expect(list.scrollTop).toBe(600);
    rerender(view(draft(8)));
    expect(list.scrollTop).toBe(800);
  });

  it("scrolls its messages inside the panel on a wide screen, with the request box below them", () => {
    render(view(draft(2)));
    const list = screen.getByRole("list", { name: "Conversation" });
    expect(list.className).toMatch(/\blg:overflow-y-auto\b/);
    expect(list.className).toMatch(/\blg:flex-1\b/);
    expect(list.compareDocumentPosition(screen.getByLabelText("Your request")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
