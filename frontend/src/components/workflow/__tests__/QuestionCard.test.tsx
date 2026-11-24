import { readFileSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CATALOG_ID } from "@/components/a2ui/catalog";
import { QuestionCard } from "@/components/workflow/QuestionCard";
import type { ActivityItem, ActivityQuestion, FormValues, SurfaceMessage } from "@/lib/types";

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
  form: null,
  answer_data: null,
};
const item = (q: Partial<ActivityQuestion> = {}): ActivityItem => ({
  type: "question",
  id: "q1",
  at: "2026-10-25T10:00:00Z",
  actor: null,
  question: { ...base, ...q },
});

function setup(
  q: Partial<ActivityQuestion> = {},
  canAct = true, answer?: Response,   extra: { readOnly?: boolean; mockupsFail?: boolean; onAnswered?: () => void; Card?: typeof QuestionCard } = {},
) {
  const Card = extra.Card ?? QuestionCard;
  const fetchMock = vi.fn(async (...args: [url: string, init?: RequestInit]) => {
    const url = args[0];
    if (url.endsWith("/answer")) return (answer ?? new Response("{}", { status: 200 })).clone();
    if (url === "/api/images") {
      return new Response(JSON.stringify({ id: "img-1", filename: "a.png", size: 4, content_type: "image/png" }), { status: 201 });
    }
    if (url.endsWith("/mockups")) {
      if (extra.mockupsFail) return new Response("{}", { status: 500 });
      return new Response(JSON.stringify([{ id: "m1", version: 2, title: "Login", choices: ["a", "b"], created_at: "x" }]), { status: 200 });
    }
    return new Response("[]", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Card item={item(q)} taskKey="PAY-1" canAct={canAct} readOnly={extra.readOnly} onAnswered={extra.onAnswered} />
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

  it("sends images with an answer in its own words", async () => {
    const { answers, sentBody } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "This one" } });
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["PNG"], "a.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send answer" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ text: "This one", image_ids: ["img-1"] });
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

// the plan's example form, as backend/app/a2ui/service.py's wrap stores it
const example = (
  JSON.parse(readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "forms.json"), "utf8")) as {
    valid: { name: string; form: { components: Record<string, unknown>[]; data: FormValues } }[];
  }
).valid.find((f) => f.name === "example")!.form;
const form: SurfaceMessage = {
  version: "1.0",
  createSurface: { surfaceId: "form-0123456789ab", catalogId: CATALOG_ID, components: example.components, dataModel: example.data },
};
const formQuestion: Partial<ActivityQuestion> = { body: "About the release", choices: [], form };
const send = () => screen.getByRole("button", { name: "Send answer" });

describe("QuestionCard with a form", () => {
  it("a form question shows the form and no choice buttons", async () => {
    setup({ ...formQuestion, choices: [{ id: "a", label: "Option A" }] });
    expect(await screen.findByLabelText("Release name")).toBeEnabled();
    expect(screen.getByRole("group", { name: "Kind" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Option A/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Other" })).toBeNull();
  });

  it("Send is off while a check fails", async () => {
    setup(formQuestion);
    const name = await screen.findByLabelText("Release name");
    expect(send()).toBeDisabled();
    await userEvent.type(name, "v1");
    await waitFor(() => expect(send()).toBeEnabled());
  });

  it("sends the form data", async () => {
    const { answers, sentBody } = setup(formQuestion);
    await userEvent.type(await screen.findByLabelText("Release name"), "v1");
    await waitFor(() => expect(send()).toBeEnabled());
    fireEvent.click(send());
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ data: { name: "v1", due: "", kind: ["patch"], notify: true } });
  });

  it("switching to own words and back keeps the form values and sends text", async () => {
    const { answers, sentBody } = setup(formQuestion);
    await userEvent.type(await screen.findByLabelText("Release name"), "v1");
    fireEvent.click(screen.getByRole("button", { name: "Answer in your own words instead" }));
    // the form stays mounted under Tailwind's `hidden` (jsdom has no stylesheet, so look for the class)
    expect(screen.getByLabelText("Release name").closest(".hidden")).not.toBeNull();
    expect(send()).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "Call it v1" } });
    expect(screen.getByText("10/4000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back to the form" }));
    expect(screen.getByLabelText("Release name").closest(".hidden")).toBeNull();
    expect(screen.getByLabelText("Release name")).toHaveValue("v1");
    expect(screen.queryByLabelText("Your answer")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Answer in your own words instead" }));
    expect(screen.getByLabelText("Your answer")).toHaveValue("Call it v1");
    fireEvent.click(send());
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ text: "Call it v1" });
  });

  it("the answered form is read-only with the sent values", async () => {
    setup({ ...formQuestion, status: "answered", answered_by: { id: "u1", name: "Sara Kim" }, answer_data: { name: "v1" } });
    const name = await screen.findByLabelText("Release name");
    expect(name).toBeDisabled();
    expect(name).toHaveValue("v1");
    expect(screen.getByText("Sara Kim answered with the form.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).toBeNull();
  });

  it("a text answer on a form question shows the text", async () => {
    setup({ ...formQuestion, status: "answered", answered_by: { id: "u1", name: "Sara Kim" }, answer_text: "Call it v1" });
    expect(screen.getByText(/Sara Kim answered:/).parentElement).toHaveTextContent("Call it v1");
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(screen.queryByLabelText("Release name")).toBeNull();
  });

  it("a withdrawn form question is read-only", async () => {
    setup({ ...formQuestion, status: "withdrawn" });
    expect(await screen.findByLabelText("Release name")).toBeDisabled();
    expect(screen.getByText(/withdrawn/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).toBeNull();
    cleanup();
    setup(formQuestion, false);
    expect(await screen.findByLabelText("Release name")).toBeDisabled();
    expect(screen.getByText("Waiting on the agent's owner, a project manager or an admin to answer.")).toBeInTheDocument();
  });
});

describe("QuestionCard when the form renderer fails", () => {
  afterEach(() => {
    vi.doUnmock("@a2ui/react");
    vi.resetModules();
  });

  it("when the renderer fails, the person can still answer in their own words", async () => {
    vi.resetModules();
    vi.doMock("@a2ui/react", () => {
      throw new Error("chunk failed to load");
    });
    const { QuestionCard: Card } = await import("@/components/workflow/QuestionCard");
    const { answers, sentBody } = setup(formQuestion, true, undefined, { Card });
    expect(await screen.findByRole("alert")).toHaveTextContent("This form couldn't be shown.");
    expect(send()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Answer in your own words instead" }));
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "Call it v1" } });
    fireEvent.click(send());
    await waitFor(() => expect(answers()).toHaveLength(1));
    expect(sentBody()).toEqual({ text: "Call it v1" });
  });
});
