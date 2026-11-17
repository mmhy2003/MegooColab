import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunningNow } from "@/components/dashboard/RunningNow";

import { NOW, run } from "./fixture";

const none = { total: 0, items: [] };

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RunningNow", () => {
  it("ticks the elapsed time without refetching", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    render(<RunningNow running={[run({ started_at: "2026-10-28T10:00:00Z" })]} queued={none} isAdmin={false} />);
    expect(screen.getByText("12 m")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByText("13 m")).toBeInTheDocument();
  });

  it("puts the link before the agent and the status", () => {
    render(<RunningNow running={[run(), run({ run_id: "r2" })]} queued={none} isAdmin={false} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    for (const li of rows) {
      const text = li.textContent!;
      expect(text.indexOf("PAY-14")).toBeGreaterThanOrEqual(0);
      expect(text.indexOf("PAY-14")).toBeLessThan(text.indexOf("Vera's Claude Code"));
      expect(text.indexOf("Vera's Claude Code")).toBeLessThan(text.indexOf("Build · Step 2 of 3"));
    }
  });

  it("a chat shows its title and a question its key", () => {
    render(
      <RunningNow
        running={[
          run({ kind: "chat", title: "Pricing ideas", chat_id: "c1", link: "/chats/c1" }),
          run({
            run_id: "r2", kind: "question", task_key: null, question_key: "PAY-Q12", stage: null, step: null, steps_total: null,
            title: null, link: "/questions/q1",
          }),
        ]}
        queued={none}
        isAdmin={false}
      />,
    );
    expect(screen.getByRole("link", { name: "Pricing ideas" })).toHaveAttribute("href", "/chats/c1");
    expect(screen.getByRole("link", { name: "PAY-Q12" })).toHaveAttribute("href", "/questions/q1");
    expect(screen.getByText("Answering")).toBeInTheDocument();
  });

  it("lists five queued keys then the rest as a number", () => {
    const items = [
      { task_key: "PAY-16", stage: "plan" as const, link: "/projects/PAY/board?task=PAY-16" },
      { task_key: "WEB-33", stage: "design" as const, link: "/projects/WEB/board?task=WEB-33" },
      { task_key: null, stage: null, link: null },
    ];
    render(<RunningNow running={[]} queued={{ total: 5, items }} isAdmin={false} />);
    const line = screen.getByText(/^Queued:/);
    expect(line).toHaveTextContent("Queued: PAY-16 Plan · WEB-33 Design · a question and 2 more");
    expect(screen.getByRole("link", { name: "PAY-16" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-16");
    expect(screen.getByRole("link", { name: "WEB-33" })).toHaveAttribute("href", "/projects/WEB/board?task=WEB-33");
  });

  it("links All runs to the admin page for admins and My agents for others", () => {
    render(<RunningNow running={[]} queued={none} isAdmin />);
    expect(screen.getByRole("link", { name: /All runs/ })).toHaveAttribute("href", "/admin/agents");
    expect(screen.getByText("No agent is running.")).toBeInTheDocument();
    cleanup();
    render(<RunningNow running={[]} queued={none} isAdmin={false} />);
    expect(screen.getByRole("link", { name: /All runs/ })).toHaveAttribute("href", "/settings/agents");
  });
});
