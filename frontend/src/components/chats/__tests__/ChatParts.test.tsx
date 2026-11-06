import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("sends the images added to the message", async () => {
    const posts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/images") {
        return new Response(JSON.stringify({ id: "img-1", filename: "a.png", size: 4, content_type: "image/png" }), { status: 201 });
      }
      if (init?.method === "POST") posts.push(JSON.parse(String(init.body)));
      return new Response("{}", { status: 200 });
    }));
    withClient(<ChatComposer chat={chat({ intent: "tell", takes_images: true })} agentRunning={false} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Message laptop-claude" }), { target: { value: "See this" } });
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["PNG"], "a.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(posts).toEqual([{ body: "See this", image_ids: ["img-1"] }]));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove a.png" })).toBeNull());
  });

  it("can't add images when the agent's runner can't take them", () => {
    stubFetch();
    withClient(<ChatComposer chat={chat({ intent: "tell", takes_images: false })} agentRunning={false} />);
    expect(screen.getByRole("button", { name: "Add images" })).toBeDisabled();
    expect(screen.getByText("Update the runner on laptop-claude's machine to send images.")).toBeInTheDocument();
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
  it("while the agent works, asks whether to stop it, and ends once confirmed", async () => {
    const calls = stubFetch();
    withClient(<EndChatButton chat={chat()} agentRunning />);
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const ask = await screen.findByRole("alertdialog", { name: "End this chat?" });
    expect(within(ask).getByText("Stop the agent and end this chat? Whatever it committed stays on its branch.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    fireEvent.click(within(ask).getByRole("button", { name: "End chat" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.url).toBe("/api/chats/c1/end"));
  });

  it("asks first even when the agent isn't working, since an ended chat can't be reopened", async () => {
    const calls = stubFetch();
    withClient(<EndChatButton chat={chat()} agentRunning={false} />);
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const ask = await screen.findByRole("alertdialog", { name: "End this chat?" });
    expect(
      within(ask).getByText("It becomes read-only and can't be reopened. To keep going, start a new chat."),
    ).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    fireEvent.click(within(ask).getByRole("button", { name: "End chat" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.url).toBe("/api/chats/c1/end"));
  });

  it("Cancel leaves the chat open", async () => {
    const calls = stubFetch();
    withClient(<EndChatButton chat={chat()} agentRunning={false} />);
    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    const ask = await screen.findByRole("alertdialog", { name: "End this chat?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
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
