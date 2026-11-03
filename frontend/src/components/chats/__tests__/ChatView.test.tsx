import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatView } from "@/components/chats/ChatView";
import { chat } from "@/components/chats/__tests__/fixtures";
import type { Chat } from "@/lib/chats";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/chats/c1",
  useSearchParams: () => new URLSearchParams(),
}));

const LONG = "are there any remaining plans unimplemented? I want a full list grouped by project, with what each one is missing";

function show(c: Chat) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("/activity") || url.includes("/agent-runs") ? [] : url.includes("/workflow") ? {} : c;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatView chatId="c1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatView", () => {
  it("the phone header folds End chat into a menu and the steps into one line", async () => {
    const r = chat().rounds[0];
    show(chat({ rounds: [{ ...r, stage: "design" }] }));
    await userEvent.click(await screen.findByRole("button", { name: "Chat actions" }));
    expect(await screen.findByRole("menuitem", { name: "End chat" })).toBeInTheDocument();
    const steps = screen.getByRole("button", { name: "Design · step 2 of 5" }); // the ▾ is not read out
    expect(steps).toHaveAttribute("aria-expanded", "false");
    expect(steps).toHaveClass("min-h-8"); // tap-sized
    await userEvent.click(steps);
    expect(steps).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("list", { name: "Progress" }).length).toBe(2); // the phone's, and the desktop row
  });

  it("on a phone the message box grows with the text and the image button sits beside Send", async () => {
    show(chat());
    const box = await screen.findByRole("textbox", { name: "Message laptop-claude" });
    expect(box).toHaveClass("max-md:[field-sizing:content]", "max-md:max-h-32");
    const images = screen.getByRole("button", { name: "Add images" });
    const send = screen.getByRole("button", { name: "Send" });
    // one row on a phone: the image button and Send share a parent row
    expect(images.closest("[data-composer-row]")).toContainElement(send);
  });

  it("the header names project, agent and program on one line", async () => {
    show(chat());
    const line = await screen.findByText("PAY · laptop-claude · Claude Code");
    expect(line).toHaveClass("truncate");
  });

  it("gives a long title its own lines, cut after two, and the whole of it on hover", async () => {
    show(chat({ title: LONG }));
    const title = await screen.findByRole("heading", { level: 2, name: LONG });
    expect(title).toHaveClass("line-clamp-2");
    expect(title).toHaveAttribute("title", LONG);
    // the details go on the line under it, not beside it
    expect(title.parentElement).not.toContainElement(screen.getByText("PAY"));
  });

  it("only the conversation scrolls: the header and the message box are outside it", async () => {
    const { container } = show(chat());
    const thread = await vi.waitFor(() => {
      const el = container.querySelector<HTMLElement>("[data-thread]");
      if (!el) throw new Error("no thread yet");
      return el;
    });
    expect(thread).toHaveClass("overflow-y-auto");
    expect(thread).not.toContainElement(screen.getByRole("heading", { level: 2 }));
    expect(thread).not.toContainElement(screen.getByRole("textbox", { name: "Message laptop-claude" }));
  });

  it("opens at the latest, following, once the conversation loads", async () => {
    show(chat());
    expect(await screen.findByText("Following live")).toBeInTheDocument();
  });

  it("makes what waits on the viewer a button that goes there", async () => {
    show(chat({ state: "question", intent: "answer" }));
    expect(await screen.findByRole("button", { name: "waiting: answer the agent's question" })).toBeInTheDocument();
  });

  it("keeps the state as text for someone who can't act on it", async () => {
    show(chat({ state: "question", can_act: false }));
    expect(await screen.findByText("waiting: answer the agent's question")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "waiting: answer the agent's question" })).toBeNull();
  });

  it("shows the images sent with a round's first message", async () => {
    const c = chat();
    show({ ...c, rounds: [{ ...c.rounds[0], images: [{ id: "i1", filename: "first.png", size: 10 }] }] } as typeof c);
    expect(await screen.findByRole("button", { name: "Open first.png" })).toBeInTheDocument();
  });
});
