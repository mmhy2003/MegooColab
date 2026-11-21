import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/chats/c1",
  useSearchParams: () => new URLSearchParams(),
}));

import { ChatComposer } from "@/components/chats/ChatComposer";
import { ChatList } from "@/components/chats/ChatList";
import { ChatView } from "@/components/chats/ChatView";
import { RoundSections } from "@/components/chats/RoundSections";
import { chat } from "@/components/chats/__tests__/fixtures";
import type { Chat } from "@/lib/chats";

const TRIGGER = { id: "tr1", name: "Bug fixed", what: "PAY-7 finished · moved to Done by Mia", keep_open: false };
const PROMPT = "Write a release note for the bug that was fixed.";

function triggered(over: Partial<Chat> = {}): Chat {
  return chat({
    mode: "freestyle", trigger: TRIGGER, started_by: { id: "u1", name: "Mia" },
    ...over,
  } as Partial<Chat>);
}

/** Answers a chat's own requests: the chat itself, its round's task with the prompt, and empty lists for the rest. */
function stubFetch(c: Chat) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const lists = ["/activity", "/agent-runs", "/questions", "/attachments", "/mockups", "/api/projects/", "/api/users"];
      const body = lists.some((l) => url.includes(l))
        ? []
        : url.includes("/workflow") ? { documents: [], can_act: true } : url.includes("/records") ? { decisions: [] }
        : url.startsWith("/api/tasks/") ? { id: "t7", key: "PAY-7", subtask_count: 0, subtask_done_count: 0, description_md: PROMPT }
        : c;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a chat a trigger started", () => {
  it("has the Trigger chip in the list, before its title, and none on other chats", () => {
    render(<ChatList chats={[triggered(), chat({ id: "c2", title: "By hand" })]} showProject={false} />);
    const [first, second] = screen.getAllByRole("link");
    const chip = within(first).getByText("Trigger");
    expect(chip.nextSibling?.textContent).toBe("Fix empty email");
    expect(within(second).queryByText("Trigger")).toBeNull();
  });

  it("has the Trigger chip in the header, beside Freestyle", async () => {
    stubFetch(triggered());
    withClient(<ChatView chatId="c1" />);
    const header = (await screen.findByText("Freestyle")).closest("header")!;
    expect(within(header).getByText("Trigger")).toBeInTheDocument();
  });

  it("shows its first message: the trigger and who it runs as, the prompt and What happened", async () => {
    const c = triggered();
    stubFetch(c);
    withClient(<RoundSections chat={c} round={c.rounds[0]} latest />);
    const first = await screen.findByRole("region", { name: "First message" });
    expect(within(first).getByRole("heading", { name: "Trigger Bug fixed · runs as Mia" })).toBeInTheDocument();
    expect(await within(first).findByText(PROMPT)).toBeInTheDocument();
    expect(within(first).getByText(PROMPT).tagName).toBe("PRE");
    expect(within(first).getByRole("heading", { name: "What happened" })).toBeInTheDocument();
    expect(within(first).getByText(TRIGGER.what).tagName).toBe("PRE");
    // it comes before the round's other parts
    const regions = screen.getAllByRole("region");
    expect(regions[0]).toBe(first);
  });

  it("a chat started by a person has no first message block", async () => {
    const c = chat();
    stubFetch(c);
    withClient(<RoundSections chat={c} round={c.rounds[0]} latest />);
    await screen.findByRole("region", { name: "Activity" });
    expect(screen.queryByRole("region", { name: "First message" })).toBeNull();
  });

  it("an ended one says it ended when the agent replied, unless it was kept open", () => {
    stubFetch(triggered());
    withClient(<ChatComposer chat={triggered({ status: "ended", intent: "closed" })} agentRunning={false} />);
    expect(screen.getByText("This chat ended when the agent replied.")).toBeInTheDocument();
    cleanup();
    withClient(
      <ChatComposer chat={triggered({ status: "ended", intent: "closed", trigger: { ...TRIGGER, keep_open: true } })} agentRunning={false} />,
    );
    expect(screen.getByText("This chat has ended.")).toBeInTheDocument();
  });
});
