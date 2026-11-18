import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { run } from "@/components/dashboard/__tests__/fixture";
import { RunLink } from "@/components/runs/RunLink";

afterEach(cleanup);

describe("RunLink", () => {
  it("links a task by its key, with its title on hover", () => {
    render(<RunLink run={run()} />);
    const link = screen.getByRole("link", { name: "PAY-14" });
    expect(link).toHaveAttribute("href", "/projects/PAY/board?task=PAY-14");
    expect(link).toHaveAttribute("title", "Fix the login");
  });

  it("tags a chat and links it by its title", () => {
    render(<RunLink run={run({ kind: "chat", title: "Pricing ideas", chat_id: "c1", link: "/chats/c1" })} />);
    expect(screen.getByText("chat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pricing ideas" })).toHaveAttribute("href", "/chats/c1");
  });

  it("links a question by its key", () => {
    render(<RunLink run={run({ kind: "question", task_key: null, question_key: "PAY-Q12", title: null, link: "/questions/q1" })} />);
    expect(screen.getByRole("link", { name: "PAY-Q12" })).toHaveAttribute("href", "/questions/q1");
  });

  it("tags a cron and links it by its name", () => {
    render(<RunLink run={run({ kind: "cron", task_key: null, title: "Nightly check", link: "/projects/PAY/crons/k1" })} />);
    expect(screen.getByText("cron")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nightly check" })).toHaveAttribute("href", "/projects/PAY/crons/k1");
  });

  it("shows a draft as text", () => {
    render(<RunLink run={run({ kind: "draft", task_key: null, title: null, link: null })} />);
    expect(screen.getByText("Knowledge Base draft")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows a run the viewer cannot open without a link", () => {
    render(<RunLink run={run({ task_key: "WEB-3", link: null })} />);
    expect(screen.getByText("WEB-3")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
