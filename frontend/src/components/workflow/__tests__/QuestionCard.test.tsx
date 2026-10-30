import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QuestionCard } from "@/components/workflow/QuestionCard";
import type { ActivityItem, ActivityQuestion } from "@/lib/types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const base: ActivityQuestion = {
  id: "q1",
  body: "Which **database**? ![x](https://evil.example/p.png)",
  choices: [
    { id: "sqlite", label: "SQLite", description: "Simple and local", recommended: false },
    { id: "pg", label: "Postgres", description: "Scales out", recommended: true },
  ],
  status: "open",
  mockup: null,
  answered_by: null,
  answer_choice: null,
  answer_text: null,
};
const item = (q: Partial<ActivityQuestion> = {}): ActivityItem => ({
  type: "question",
  id: "q1",
  at: "2026-10-25T10:00:00Z",
  actor: null,
  question: { ...base, ...q },
});

function setup(q: Partial<ActivityQuestion> = {}, canAct = true, answer?: Response, extra: { readOnly?: boolean; mockupsFail?: boolean; onAnswered?: () => void } = {}) {
  const fetchMock = vi.fn(async (...args: [url: string, init?: RequestInit]) => {
    const url = args[0];
    if (url.endsWith("/answer")) return (answer ?? new Response("{}", { status: 200 })).clone();
    if (url.endsWith("/mockups")) {
      if (extra.mockupsFail) return new Response("{}", { status: 500 });
      return new Response(JSON.stringify([{ id: "m1", version: 2, title: "Login", choices: ["a", "b"], created_at: "x" }]), { status: 200 });
    }
    return new Response("[]", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <QuestionCard item={item(q)} taskKey="PAY-1" canAct={canAct} readOnly={extra.readOnly} onAnswered={extra.onAnswered} />
    </QueryClientProvider>,
  );
  const answers = () => fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/answer"));
  const sentBody = () => JSON.parse(String(answers()[0][1]?.body));
  return { answers, sentBody };
}

function mockupMessage(frame: HTMLIFrameElement, choice: string) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { source: frame.contentWindow, origin: "null", data: { type: "megoo-choice", choice } }));
  });
}

describe("QuestionCard", () => {
  it("lists the recommended choice first with descriptions, markdown body and images as links", () => {
    setup();
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toContain("Postgres (Recommended)");
    expect(buttons[0]).toContain("Scales out");
    expect(buttons[1]).toContain("SQLite");
    expect(buttons[2]).toBe("Other");
    expect(screen.getByText("database").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "x" })).toHaveAttribute("href", "https://evil.example/p.png");
  });

  it("sends the choice id as soon as one of its own choice buttons is clicked", async () => {
    const { answers, sentBody } = setup();
    fireEvent.click(screen.getByRole("button", { name: /SQLite/ }));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(answers()[0][0]).toBe("/api/tasks/PAY-1/questions/q1/answer");
    expect(sentBody()).toEqual({ choice: "sqlite" });
  });

  it("sends free text on Other, with a counter and a 4,000 character limit", async () => {
    const { answers, sentBody } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Other" }));
    const box = screen.getByLabelText("Your answer");
    expect(box).toHaveAttribute("maxlength", "4000");
    expect(screen.getByRole("button", { name: "Send answer" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "  MySQL  " } });
    expect(screen.getByText("9/4000")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ text: "MySQL" });
  });

  it("says someone already answered on a 409", async () => {
    setup({}, true, new Response(JSON.stringify({ detail: "already_decided" }), { status: 409 }));
    fireEvent.click(screen.getByRole("button", { name: /SQLite/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone already answered.");
  });

  it("marks itself as waiting on the person only while they can answer it", () => {
    const marked = (selector = "[data-waiting]") => document.body.querySelector(selector);
    setup({});
    expect(marked('[data-waiting="question"]')).not.toBeNull();
    cleanup();
    setup({}, false);
    expect(marked()).toBeNull();
    cleanup();
    setup({}, true, undefined, { readOnly: true });
    expect(marked()).toBeNull();
    cleanup();
    setup({ status: "answered", answered_by: { id: "u1", name: "Sara Kim" }, answer_choice: "pg" });
    expect(marked()).toBeNull();
  });

  it("shows no answer controls without permission, and who answered afterwards", () => {
    setup({}, false);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Waiting on the agent's owner, a project manager or an admin to answer.")).toBeInTheDocument();
    cleanup();
    setup({}, true, undefined, { readOnly: true });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("This is a read-only view.")).toBeInTheDocument();
    cleanup();
    setup({ status: "answered", answered_by: { id: "u1", name: "Sara Kim" }, answer_choice: "pg" });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/Sara Kim answered:/).parentElement).toHaveTextContent("Postgres");
    cleanup();
    setup({ status: "answered", answered_by: { id: "u1", name: "Sara Kim" }, answer_text: "MySQL" });
    expect(screen.getByText(/Sara Kim answered:/).parentElement).toHaveTextContent("MySQL");
    cleanup();
    setup({ status: "withdrawn" });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/withdrawn/)).toBeInTheDocument();
  });

  it("a mockup choice only preselects; nothing is sent until Send answer is pressed", async () => {
    const { answers, sentBody } = setup({
      mockup: { id: "m1", version: 2, title: "Login" },
      choices: [{ id: "a", label: "Option A" }, { id: "b", label: "Option B" }],
    });
    const frame = (await screen.findByTitle("Mockup v2: Login")) as HTMLIFrameElement;
    mockupMessage(frame, "b");
    expect(screen.getByRole("button", { name: /Option B/ })).toHaveAttribute("aria-pressed", "true");
    expect(answers()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ choice: "b" });
  });

  it("ignores a mockup message when the viewer cannot answer", async () => {
    const { answers } = setup({ mockup: { id: "m1", version: 2, title: "Login" } }, false);
    const frame = (await screen.findByTitle("Mockup v2: Login")) as HTMLIFrameElement;
    mockupMessage(frame, "a");
    expect(answers()).toHaveLength(0);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not let a mockup replace text typed under Other", async () => {
    setup({ mockup: { id: "m1", version: 2, title: "Login" } });
    const frame = (await screen.findByTitle("Mockup v2: Login")) as HTMLIFrameElement;
    fireEvent.click(screen.getByRole("button", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "my own words" } });
    mockupMessage(frame, "a");
    expect(screen.getByLabelText("Your answer")).toHaveValue("my own words");
    expect(screen.getByRole("button", { name: "Other" })).toHaveAttribute("aria-pressed", "true");
  });

  it("can preselect and send a choice id that only the mockup declares", async () => {
    const { answers, sentBody } = setup({ mockup: { id: "m1", version: 2, title: "Login" }, choices: [{ id: "x", label: "X" }] });
    const frame = (await screen.findByTitle("Mockup v2: Login")) as HTMLIFrameElement;
    mockupMessage(frame, "b");
    expect(screen.getByText("Selected in the mockup: b")).toBeInTheDocument();
    expect(answers()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ choice: "b" });
  });

  it("says so when the mockup cannot be loaded", async () => {
    setup({ mockup: { id: "m1", version: 2, title: "Login" } }, true, undefined, { mockupsFail: true });
    expect(await screen.findByText("Couldn't load the mockup.")).toBeInTheDocument();
  });

  it("tells the thread after an answer, also when it conflicts", async () => {
    const onAnswered = vi.fn();
    setup({}, true, new Response(JSON.stringify({ detail: "already_decided" }), { status: 409 }), { onAnswered });
    fireEvent.click(screen.getByRole("button", { name: /SQLite/ }));
    await waitFor(() => expect(onAnswered).toHaveBeenCalled());
  });
});
