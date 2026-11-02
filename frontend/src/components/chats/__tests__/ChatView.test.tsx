import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

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

// jsdom does no scrolling
beforeAll(() => {
  Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatView", () => {
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
});
