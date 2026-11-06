import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
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

function show(c: Chat, workflow: Record<string, unknown> = {}) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (method !== "GET") return new Response(JSON.stringify({}), { status: 200 });
      // the round's own parts (RoundSections) as a task's: empty lists, no documents, no decisions
      const lists = ["/activity", "/agent-runs", "/questions", "/attachments", "/mockups", "/api/projects/", "/api/users"];
      const body = lists.some((l) => url.includes(l))
        ? []
        : url.includes("/workflow") ? workflow : url.includes("/records") ? { decisions: [] }
        : url.startsWith("/api/tasks/") ? { id: "t7", key: "PAY-7", subtask_count: 0, subtask_done_count: 0 }
        : c;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return Object.assign(
    render(
      <QueryClientProvider client={client}>
        <ChatView chatId="c1" />
      </QueryClientProvider>,
    ),
    { calls },
  );
}

/** A chat whose round stopped on an escalation, and its workflow. */
function escalated(reason: string, canAct = true): [Chat, Record<string, unknown>] {
  const c = chat({ state: "escalation", intent: "retry", can_act: canAct });
  const r = { ...c.rounds[0], stage: "build" as const, status: "waiting_human" as const, needs: "escalation" as const };
  return [
    { ...c, rounds: [r] } as Chat,
    { driver: "runner", stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: reason,
      can_act: canAct, documents: [], steps: [], pull_request: null },
  ];
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("ChatView", () => {
  it("End chat in the phone's menu asks first too", async () => {
    show(chat());
    await userEvent.click(await screen.findByRole("button", { name: "Chat actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "End chat" }));
    expect(await screen.findByRole("alertdialog", { name: "End this chat?" })).toBeInTheDocument();
  });

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
    // and holds what is positioned inside it (screen-reader text in its parts), or that would stretch the page
    expect(thread).toHaveClass("relative");
    expect(thread).not.toContainElement(screen.getByRole("heading", { level: 2 }));
    expect(thread).not.toContainElement(screen.getByRole("textbox", { name: "Message laptop-claude" }));
  });

  it("leaves room under the newest line, where the \"Following live\" note sits", async () => {
    const { container } = show(chat());
    const thread = await vi.waitFor(() => {
      const el = container.querySelector<HTMLElement>("[data-thread]");
      if (!el) throw new Error("no thread yet");
      return el;
    });
    expect(thread.lastElementChild).toHaveAttribute("data-follow-room");
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

  it("shows an escalation with its reason and actions, and Retry decides it", async () => {
    const { calls } = show(...escalated("retries_exhausted"));
    const box = await screen.findByRole("region", { name: "Escalation" });
    expect(within(box).getByText("The agent's runs failed 3 times in a row.")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: "Accept" })).toBeNull(); // not allowed for failed runs
    await userEvent.click(within(box).getByRole("button", { name: "Retry" }));
    await vi.waitFor(() =>
      expect(calls.find((x) => x.method === "POST")).toEqual({
        url: "/api/tasks/PAY-7/workflow/escalation", method: "POST", body: { action: "retry" },
      }),
    );
  });

  it("an unconfirmed merge's escalation offers Mark merged", async () => {
    show(...escalated("merge_not_confirmed"));
    const box = await screen.findByRole("region", { name: "Escalation" });
    expect(within(box).getByRole("button", { name: "Mark merged" })).toBeInTheDocument();
  });

  it("the header's waiting note goes to the escalation", async () => {
    show(...escalated("retries_exhausted"));
    expect(await screen.findByRole("button", { name: "waiting: decide the escalation" })).toBeInTheDocument();
    expect(document.body.querySelector('[data-waiting="escalation"]')).toContainElement(
      await screen.findByRole("button", { name: "Retry" }),
    );
  });

  it("someone who can't act sees the escalation without its actions", async () => {
    show(...escalated("retries_exhausted", false));
    const box = await screen.findByRole("region", { name: "Escalation" });
    expect(within(box).getByText("The agent's runs failed 3 times in a row.")).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows the images sent with a round's first message", async () => {
    const c = chat();
    show({ ...c, rounds: [{ ...c.rounds[0], images: [{ id: "i1", filename: "first.png", size: 10 }] }] } as typeof c);
    expect(await screen.findByRole("button", { name: "Open first.png" })).toBeInTheDocument();
  });
});

describe("ChatView expanded", () => {
  const card = () => screen.getByRole("heading", { level: 2 }).closest("[data-chat]") as HTMLElement;

  it("a desktop button expands the chat over the whole window, and collapses it again", async () => {
    show(chat());
    const expand = await screen.findByRole("button", { name: "Expand chat" });
    expect(expand.parentElement).toHaveClass("max-md:hidden"); // desktop only
    expect(card()).not.toHaveClass("md:fixed");
    await userEvent.click(expand);
    expect(card()).toHaveClass("md:fixed", "md:inset-0");
    // the conversation and the message box keep to a readable column
    expect(document.querySelector("[data-thread] > div")).toHaveClass("md:max-w-[56rem]", "md:mx-auto");
    await userEvent.click(screen.getByRole("button", { name: "Collapse chat" }));
    expect(card()).not.toHaveClass("md:fixed");
    expect(screen.getByRole("button", { name: "Expand chat" })).toBeInTheDocument();
  });

  it("is remembered in this browser", async () => {
    show(chat());
    await userEvent.click(await screen.findByRole("button", { name: "Expand chat" }));
    cleanup();
    show(chat());
    expect(await screen.findByRole("button", { name: "Collapse chat" })).toBeInTheDocument();
    expect(card()).toHaveClass("md:fixed");
  });

  it("Esc collapses it", async () => {
    show(chat());
    await userEvent.click(await screen.findByRole("button", { name: "Expand chat" }));
    await userEvent.keyboard("{Escape}");
    expect(card()).not.toHaveClass("md:fixed");
  });

  it("Esc closes an open menu first, and leaves the chat expanded", async () => {
    show(chat());
    await userEvent.click(await screen.findByRole("button", { name: "Expand chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Chat actions" }));
    expect(await screen.findByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(card()).toHaveClass("md:fixed");
  });

  it("Esc does nothing on a narrow screen, where expanding doesn't show", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: !q.includes("min-width"), media: q, addEventListener() {}, removeEventListener() {} }));
    show(chat());
    await userEvent.click(await screen.findByRole("button", { name: "Expand chat" }));
    await userEvent.keyboard("{Escape}");
    expect(card()).toHaveClass("md:fixed");
  });

  it("a freestyle chat shows a Freestyle chip instead of the progress steps", async () => {
    const c = chat({ mode: "freestyle", state: "reply", intent: "turn" });
    show(c);
    expect(await screen.findByText("Freestyle")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /step \d of 5/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("waiting for your reply").length).toBeGreaterThan(0);
    expect(screen.getByText("laptop-claude starts working on your message.")).toBeInTheDocument();
  });

  it("a workflow chat has no Freestyle chip and still shows the progress", async () => {
    show(chat());
    expect(await screen.findByRole("list", { name: "Progress" })).toBeInTheDocument();
    expect(screen.queryByText("Freestyle")).not.toBeInTheDocument();
  });
});
