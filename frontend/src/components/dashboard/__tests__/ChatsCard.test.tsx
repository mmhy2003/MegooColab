import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatsCard } from "@/components/dashboard/ChatsCard";
import { FinishedChart } from "@/components/dashboard/FinishedChart";
import type { ChatBrief } from "@/lib/dashboard";

afterEach(cleanup);

const brief = (over: Partial<ChatBrief> = {}): ChatBrief => ({
  id: "c1", title: "Fix empty email", project_key: "PAY", state: "plan_approval", current_step: null, steps_total: null,
  pr_url: null, finish_outcome: null, agent_name: "laptop-claude", ...over,
});

describe("ChatsCard", () => {
  it("lists open chats with what each is doing, and links to all chats and a new one", () => {
    render(<ChatsCard chats={[brief(), brief({ id: "c2", title: "Bump axios", project_key: "WEB", state: "building", current_step: 2, steps_total: 3 })]} />);
    const card = screen.getByRole("region", { name: "Chats" });
    const rows = within(card).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("Fix empty email · PAY");
    expect(rows[0]).toContain("waiting: approve the plan");
    expect(rows[1]).toContain("building step 2 of 3");
    expect(within(card).getByRole("link", { name: "Fix empty email · PAY" })).toHaveAttribute("href", "/chats/c1");
    expect(within(card).getByRole("link", { name: "New chat" })).toHaveAttribute("href", "/chats?new=1");
    expect(within(card).getByRole("link", { name: /^All chats/ })).toHaveAttribute("href", "/chats");
  });

  it("says when there are none", () => {
    render(<ChatsCard chats={[]} />);
    expect(screen.getByText("No open chats.")).toBeInTheDocument();
  });
});

describe("FinishedChart with chats", () => {
  it("adds chats as a third series", () => {
    render(<FinishedChart days={[{ day: "2026-10-28", agents: 2, people: 1, chats: 3 }]} />);
    expect(screen.getByRole("region", { name: "Finished · last 14 days" })).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("Finished in the last 14 days: 2 tasks by agents, 1 by people, 3 chats");
    expect(screen.getByText("chats · 3")).toBeInTheDocument();
  });
});
