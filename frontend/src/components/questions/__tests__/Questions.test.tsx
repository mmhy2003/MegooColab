import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnswerForm } from "@/components/questions/AnswerForm";
import { AskQuestion } from "@/components/questions/AskQuestion";
import { DraftReview } from "@/components/questions/DraftReview";
import { QuestionView } from "@/components/questions/QuestionView";
import { TaskQuestions, WaitingBadge } from "@/components/questions/TaskQuestions";
import { invalidationsFor } from "@/lib/realtime";
import type { Question } from "@/lib/questions";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/questions" }));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const nobody = { user: null, agent: null };
const Q: Question = {
  id: "q1",
  ref: "PAY-Q1",
  target: { key: "PAY", name: "Payments" },
  title: "How are webhooks signed?",
  body: "How are webhooks signed?",
  context: "",
  status: "queued",
  answer_md: null,
  citations: [],
  answer_source: null,
  answered_by: nobody,
  answering: null,
  draft: null,
  reject_reason: null,
  redacted: false,
  attempts: 0,
  from_task: null,
  asked_by: { user: { id: "u1", name: "Ann" }, agent: null },
  kb_document_id: null,
  created_at: "2026-10-26T10:00:00Z",
  answered_at: null,
  can_answer: false,
  can_approve: false,
  can_withdraw: false,
};
const AGENT = { user: { id: "u2", name: "Bob" }, agent: { id: "a1", name: "Bob's Claude" } };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AskQuestion", () => {
  it("shows suggestions before asking and asks anyway", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/questions/targets") return json([{ key: "PAY", name: "Payments" }]);
      if (url === "/api/questions/suggest")
        return json([{ kind: "kb", id: "d1", title: "Q3: Webhook signing", snippet: "HMAC", link: "/kb/doc/d1" }]);
      if (url === "/api/questions" && init?.method === "POST") return json({ question: Q, suggestions: [] }, 201);
      return json([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onAsked = vi.fn();
    wrap(<AskQuestion taskKey="WEB-4" onAsked={onAsked} />);
    await screen.findByRole("option", { name: "PAY — Payments" });
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "PAY" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How are webhooks signed?" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for existing answers" }));
    const link = await screen.findByRole("link", { name: "Q3: Webhook signing" });
    expect(link).toHaveAttribute("href", "/kb/doc/d1");
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/questions")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Ask anyway" }));
    await waitFor(() => expect(onAsked).toHaveBeenCalledWith("q1"));
    const [, init] = fetchMock.mock.calls.find(([u, i]) => u === "/api/questions" && i?.method === "POST")!;
    expect(JSON.parse(String(init!.body))).toEqual({
      project_key: "PAY", body: "How are webhooks signed?", context: "", task_key: "WEB-4",
    });
  });

  it("shows the open-question cap as a clear error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/questions/targets"
          ? json([{ key: "PAY", name: "Payments" }])
          : url === "/api/questions/suggest"
            ? json([])
            : json({ detail: "too_many_open_questions" }, 429),
      ),
    );
    wrap(<AskQuestion />);
    await screen.findByRole("option", { name: "PAY — Payments" });
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "PAY" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Anything?" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for existing answers" }));
    expect(await screen.findByText("No existing answers found.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask anyway" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You have 20 open questions");
  });
});

describe("QuestionView", () => {
  it("status lines for every status", () => {
    const cases: [Partial<Question>, string][] = [
      [{ status: "queued" }, "Waiting for a runner of PAY"],
      [{ status: "routed", answering: AGENT }, "Being answered by Bob's Claude"],
      [{ status: "draft", answering: AGENT }, "Draft awaiting Bob's approval"],
      [{ status: "needs_human" }, "Needs a human answer"],
      [{ status: "answered", answer_md: "x", answered_by: { user: { id: "u3", name: "Cy" }, agent: null } }, "Answered by Cy"],
      [{ status: "answered", answer_md: "x", answered_by: AGENT }, "Answered by Bob's Claude (Bob)"],
      [{ status: "withdrawn" }, "Withdrawn"],
    ];
    for (const [patch, line] of cases) {
      wrap(<QuestionView question={{ ...Q, ...patch }} />);
      expect(screen.getByText(line)).toBeInTheDocument();
      cleanup();
    }
  });

  it("renders answer markdown, citations and redacted notice", () => {
    wrap(
      <QuestionView
        question={{
          ...Q,
          status: "answered",
          answer_md: "Signed with **HMAC** in `sign.py`.",
          citations: [{ path: "app/sign.py", start_line: 3, end_line: 9 }],
          redacted: true,
          kb_document_id: "d9",
          answered_by: AGENT,
        }}
      />,
    );
    expect(screen.getByText("HMAC").tagName).toBe("STRONG");
    expect(screen.getByText("app/sign.py:3-9")).toHaveClass("font-mono");
    expect(screen.getByText("Secrets were removed from this answer.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View in Knowledge Base" })).toHaveAttribute("href", "/kb/doc/d9");
  });

  it("question text renders without raw html", () => {
    const { container } = wrap(
      <QuestionView
        question={{
          ...Q,
          status: "answered",
          body: "<img src=x onerror=alert(1)> body",
          answer_md: "<script>alert(1)</script><b>bold?</b>",
          answered_by: AGENT,
        }}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)> body/)).toBeInTheDocument();
  });

  it("withdraw shows only when allowed", async () => {
    const fetchMock = vi.fn(async () => json({ ...Q, status: "withdrawn" }));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<QuestionView question={Q} />);
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
    cleanup();
    wrap(<QuestionView question={{ ...Q, can_withdraw: true }} />);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/questions/q1/withdraw", expect.anything()));
  });
});

describe("DraftReview", () => {
  const draftQ: Question = {
    ...Q,
    status: "draft",
    can_approve: true,
    answering: AGENT,
    draft: { answer_md: "Draft text", citations: [{ path: "a.py", start_line: 1, end_line: 2 }], agent: AGENT.agent },
  };

  it("approve sends edit and reject requires reason", async () => {
    const fetchMock = vi.fn(async () => json({ ...draftQ, status: "answered" }));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<DraftReview question={draftQ} />);
    fireEvent.change(screen.getByLabelText("Draft answer text"), { target: { value: "Edited text" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/questions/q1/approve");
    expect(JSON.parse(String(init.body))).toEqual({ answer_md: "Edited text" });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const submit = screen.getByRole("button", { name: "Reject draft" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Why is it wrong/), { target: { value: "Stale file" } });
    fireEvent.click(submit);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [rurl, rinit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(rurl).toBe("/api/questions/q1/reject");
    expect(JSON.parse(String(rinit.body))).toEqual({ reason: "Stale file" });
  });

  it("approve without an edit sends no text, and nothing shows without can_approve", async () => {
    const fetchMock = vi.fn(async () => json(draftQ));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<DraftReview question={draftQ} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body))).toEqual({});
    cleanup();
    wrap(<DraftReview question={{ ...draftQ, can_approve: false }} />);
    expect(screen.queryByRole("region", { name: "Draft answer" })).toBeNull();
  });
});

describe("AnswerForm", () => {
  it("only when can_answer", async () => {
    wrap(<AnswerForm question={Q} />);
    expect(screen.queryByRole("form", { name: "Answer" })).toBeNull();
    cleanup();
    const fetchMock = vi.fn(async () => json({ ...Q, status: "answered" }));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<AnswerForm question={{ ...Q, status: "routed", can_answer: true }} />);
    expect(screen.getByText("Answering now stops the agent that is working on it.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Answer it yourself"), { target: { value: "HMAC." } });
    fireEvent.click(screen.getByRole("button", { name: "Post answer" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/questions/q1/answer");
    expect(JSON.parse(String(init.body))).toEqual({ answer_md: "HMAC." });
  });
});

describe("TaskQuestions", () => {
  it("TaskQuestions and waiting badge", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([{ ...Q, status: "routed", answering: AGENT }])));
    wrap(<TaskQuestions taskKey="WEB-4" />);
    expect(await screen.findByRole("link", { name: "How are webhooks signed?" })).toHaveAttribute("href", "/questions/q1");
    expect(screen.getByText("Being answered by Bob's Claude")).toBeInTheDocument();
    cleanup();
    wrap(<WaitingBadge projects={["PAY", "OPS"]} />);
    expect(screen.getByText("Waiting on PAY, OPS")).toBeInTheDocument();
    cleanup();
    const { container } = wrap(<WaitingBadge projects={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("asks another project from the task", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/questions/targets") return json([{ key: "PAY", name: "Payments" }]);
      if (url === "/api/questions/suggest") return json([]);
      if (url === "/api/questions" && init?.method === "POST") return json({ question: Q, suggestions: [] }, 201);
      return json([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    wrap(<TaskQuestions taskKey="WEB-4" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ask another project" }));
    await screen.findByRole("option", { name: "PAY — Payments" });
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "PAY" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Which port?" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for existing answers" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ask anyway" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Ask a project" })).toBeNull());
    const [, init] = fetchMock.mock.calls.find(([u, i]) => u === "/api/questions" && i?.method === "POST")!;
    expect(JSON.parse(String(init!.body)).task_key).toBe("WEB-4");
  });

  it("question events refresh questions and tasks", () => {
    expect(invalidationsFor({ type: "question.updated", user_id: "u1" }, new Map())).toEqual([["questions"], ["task"]]);
  });
});
