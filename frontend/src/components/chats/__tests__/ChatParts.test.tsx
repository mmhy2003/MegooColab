import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BoardDialog } from "@/components/chats/BoardDialog";
import { ChatComposer } from "@/components/chats/ChatComposer";
import { EndChatButton } from "@/components/chats/EndChatButton";
import { RoundDivider } from "@/components/chats/RoundDivider";
import { chat } from "@/components/chats/__tests__/fixtures";

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function stubFetch(responses: Record<string, unknown> = {}) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = Object.entries(responses).find(([k]) => url.includes(k));
    return new Response(JSON.stringify(hit ? hit[1] : {}), { status: method === "POST" ? 201 : 200 });
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatComposer", () => {
  it("says what the message will do, sends it and clears", async () => {
    const calls = stubFetch();
    withClient(<ChatComposer chat={chat({ intent: "answer" })} agentRunning={false} />);
    expect(screen.getByText("Your message answers laptop-claude's question.")).toBeInTheDocument();
    const box = screen.getByRole("textbox", { name: "Message laptop-claude" });
    fireEvent.change(box, { target: { value: "Postgres" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toMatchObject({ url: "/api/chats/c1/messages", body: { body: "Postgres" } }));
    await waitFor(() => expect(box).toHaveValue(""));
  });

  it("is replaced when the chat has ended", () => {
    stubFetch();
    withClient(<ChatComposer chat={chat({ status: "ended", intent: "closed" })} agentRunning={false} />);
    expect(screen.getByText("This chat has ended.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("BoardDialog", () => {
  const round = { ...chat().rounds[0], board: "pending" as const };

  it("proposes the details and creates the task", async () => {
    const calls = stubFetch({
      "/board": { title: "Fix empty email", description_md: "Asked.\n\n**Outcome:** merged", column_id: "col-done" },
      "/columns": [{ id: "col-todo", name: "To Do", category: "before" }, { id: "col-done", name: "Done", category: "done" }],
    });
    withClient(<BoardDialog chat={chat()} round={round} />);
    expect(await screen.findByRole("heading", { name: "Add this to the board?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Fix empty email"));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Fix the empty email crash" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toMatchObject({
      url: "/api/chats/c1/rounds/1/board",
      body: { add: true, title: "Fix the empty email crash", description_md: "Asked.\n\n**Outcome:** merged", column_id: "col-done" },
    }));
  });

  it("can leave it out", async () => {
    const calls = stubFetch({ "/board": { title: "T", description_md: "D", column_id: "c" }, "/columns": [] });
    withClient(<BoardDialog chat={chat()} round={round} />);
    fireEvent.click(await screen.findByRole("button", { name: "No, just end it" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toMatchObject({ body: { add: false } }));
  });
});

describe("EndChatButton", () => {
  it("asks first while the agent is working, and ends at once otherwise", async () => {
    const calls = stubFetch();
    const { rerender } = withClient(<EndChatButton chat={chat()} agentRunning />);
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    expect(await screen.findByText("Stop the agent and end this chat? Whatever it committed stays on its branch.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    cleanup();
    withClient(<EndChatButton chat={chat()} agentRunning={false} />);
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.url).toBe("/api/chats/c1/end"));
    void rerender;
  });
});

describe("RoundDivider", () => {
  it("names the round and where it starts from", () => {
    stubFetch();
    const r = { ...chat().rounds[0], n: 2, title: "Add retries", branch_from: "megoo/PAY-7-fix" };
    withClient(<RoundDivider round={r} canEdit={false} />);
    expect(screen.getByText("Round 2 · Add retries")).toBeInTheDocument();
    expect(screen.getByText("from megoo/PAY-7-fix")).toBeInTheDocument();
  });
});
