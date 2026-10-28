import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NeedsYou } from "@/components/dashboard/NeedsYou";

import { need } from "./fixture";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function wrap(ui: ReactNode, client = new QueryClient()) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("NeedsYou", () => {
  it("labels each row and links it to the task", () => {
    wrap(<NeedsYou items={[need("design_approval", "PAY-12", "Refund flow")]} total={1} showWaitingFor={false} />);
    expect(screen.getByText("Approve design")).toBeInTheDocument();
    expect(screen.getByText("Refund flow")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review PAY-12" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-12");
    expect(screen.getByRole("link", { name: /Open all/ })).toHaveAttribute("href", "/notifications");
  });

  it("words each kind of row", () => {
    wrap(
      <NeedsYou
        total={5}
        showWaitingFor={false}
        items={[
          need("question", "PAY-15", "Refunds", { detail: "Should refunds over $500 need a second approver?" }),
          need("escalation", "API-8", "CI", { detail: "review_rounds_exhausted" }),
          need("human_code_review", "WEB-27", "Settings tabs", { detail: "https://example.test/pr/41" }),
          need("draft_answer", "API-Q3", "Retry policy?", { link: "/questions/q3" }),
          need("needs_human", "PAY-Q4", "Who owns billing?", { link: "/questions/q4" }),
        ]}
      />,
    );
    expect(screen.getByText("“Should refunds over $500 need a second approver?”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Answer PAY-15" })).toBeInTheDocument();
    expect(screen.getByText("Stuck")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Look API-8" })).toBeInTheDocument();
    expect(screen.getByText("Pull request · Settings tabs")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check API-Q3" })).toHaveAttribute("href", "/questions/q3");
    expect(screen.getByText("Question needs a person")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Answer PAY-Q4" })).toHaveAttribute("href", "/questions/q4");
  });

  it("Reply marks the mention read, refetches at once, then opens the task", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const mention = need("mention", "PAY-1", "Pat mentioned you", {
      detail: "can you check?", notification_id: "n1", link: "/projects/PAY/board?task=PAY-1",
    });
    wrap(<NeedsYou items={[mention]} total={1} showWaitingFor={false} />, client);
    expect(screen.getByText("Pat mentioned you: “can you check?”")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reply PAY-1" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/PAY/board?task=PAY-1"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/notifications/n1/read");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-count"] });
  });

  it("names who each row waits for under My teams", () => {
    wrap(<NeedsYou items={[need("escalation", "PAY-2", "x", { waiting_for: ["Ana", "Omar"] })]} total={1} showWaitingFor />);
    expect(screen.getByText("waits for Ana, Omar")).toBeInTheDocument();
  });

  it("says when nothing needs you", () => {
    wrap(<NeedsYou items={[]} total={0} showWaitingFor={false} />);
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
  });
});
