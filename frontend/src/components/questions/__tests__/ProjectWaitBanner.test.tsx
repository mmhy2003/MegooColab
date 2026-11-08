import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectWaitBanner } from "@/components/questions/ProjectWaitBanner";
import type { ProjectWait } from "@/lib/questions";

const ANS: ProjectWait = {
  question_id: "q3", ref: "ANS-Q3", project_key: "ANS", title: "Which header carries the signature?",
  status: "routed", can_answer: true, can_withdraw: true,
};
const PAY: ProjectWait = {
  question_id: "q7", ref: "PAY-Q7", project_key: "PAY", title: "What does the refund webhook send?",
  status: "needs_human", can_answer: false, can_withdraw: false,
};

function stubFetch() {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    return new Response("{}", { status: 200 });
  }));
  return calls;
}

function show(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProjectWaitBanner", () => {
  it("says whose answer it waits for, and where each question stands", () => {
    stubFetch();
    show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS]} canAct />);
    const box = screen.getByRole("status");
    expect(within(box).getByText("Waiting for ANS's answer (ANS-Q3)")).toBeInTheDocument();
    expect(within(box).getByText(/can't go on without the answer\. It picks up again on its own/)).toBeInTheDocument();
    expect(within(box).getByText("an agent of ANS is answering")).toBeInTheDocument();
    expect(within(box).getByRole("link", { name: "Answer it yourself" })).toHaveAttribute("href", "/questions/q3");
  });

  it("two at once: answers from both projects, and each question's own rights", () => {
    stubFetch();
    show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS, PAY]} canAct />);
    expect(screen.getByText("Waiting for answers from ANS and PAY (2)")).toBeInTheDocument();
    expect(screen.getByText("waiting for a person at PAY")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Answer it yourself" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Withdraw/ })).toHaveLength(1);
  });

  it("in a chat, says a message now goes with the answer", () => {
    stubFetch();
    show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS]} canAct agentName="laptop-claude" inChat />);
    expect(screen.getByText(/laptop-claude picks up again on its own when the answer arrives\. Anything you send now reaches it with the answer\./)).toBeInTheDocument();
  });

  it("Go on without it only for those who may act, and it asks the server", async () => {
    const calls = stubFetch();
    const onChanged = vi.fn();
    const { unmount } = show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS]} canAct={false} />);
    expect(screen.queryByRole("button", { name: "Go on without it" })).toBeNull();
    unmount();
    show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS]} canAct onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Go on without it" }));
    await waitFor(() => expect(calls).toContainEqual({ url: "/api/tasks/ASK-1/project-waits/go-on", method: "POST" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("withdraws a question after asking first", async () => {
    const calls = stubFetch();
    show(<ProjectWaitBanner taskKey="ASK-1" waits={[ANS]} canAct />);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw ANS-Q3" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(calls).toContainEqual({ url: "/api/questions/q3/withdraw", method: "POST" }));
  });
});
