import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatList } from "@/components/chats/ChatList";
import { chat } from "@/components/chats/__tests__/fixtures";
import { intentText, stateText } from "@/lib/chats";

afterEach(cleanup);


describe("chat copy", () => {
  it.each([
    ["talking", {}, "talking"],
    ["question", {}, "waiting: answer the agent's question"],
    ["design_approval", {}, "waiting: approve the design"],
    ["plan_approval", {}, "waiting: approve the plan"],
    ["escalation", {}, "waiting: decide the escalation"],
    ["in_review", {}, "in review"],
    ["offline", {}, "offline — starts when laptop-claude's runner connects"],
    ["ended", {}, "ended"],
  ] as const)("state %s reads %s", (state, _over, text) => {
    expect(stateText(chat({ state }))).toBe(text);
  });

  it("names the step, the pull request and the merge", () => {
    const r = chat().rounds[0];
    expect(stateText(chat({ state: "building", rounds: [{ ...r, current_step: 2, steps_total: 3 }] }))).toBe("building step 2 of 3");
    expect(stateText(chat({ state: "human_code_review", rounds: [{ ...r, pr_url: "https://g.io/pull/42" }] }))).toBe("in code review · PR #42");
    expect(stateText(chat({ state: "finished", rounds: [{ ...r, finish_outcome: "pr_opened", pr_url: "https://g.io/pull/42" }] }))).toBe("finished · PR #42");
    expect(stateText(chat({ state: "finished", rounds: [{ ...r, finish_outcome: "merged_local" }] }))).toBe("finished · merged");
  });

  it("says what a message does", () => {
    expect(intentText(chat({ intent: "answer" }), false)).toBe("Your message answers laptop-claude's question.");
    expect(intentText(chat({ intent: "changes", rounds: [{ ...chat().rounds[0], needs: "plan_approval" }] }), false)).toBe(
      "Your message asks laptop-claude to change the plan. Approve stays on the card.",
    );
    expect(intentText(chat({ intent: "tell" }), true)).toBe("laptop-claude reads this straight away, without stopping.");
    expect(intentText(chat({ intent: "tell" }), false)).toBe("laptop-claude gets this when its next run starts.");
    expect(intentText(chat({ intent: "restart" }), false)).toBe("Your message starts laptop-claude again.");
    expect(intentText(chat({ intent: "new_round" }), false)).toBe(
      "Starts a new round: the agent talks it through, then design, plan, build and finish again.",
    );
  });
});

describe("ChatList", () => {
  it("lists chats in the order given, with the project key only across projects", () => {
    const chats = [chat({ id: "c1", title: "Waiting one", state: "plan_approval" }), chat({ id: "c2", title: "Busy one", project_key: "WEB" })];
    const { rerender } = render(<ChatList chats={chats} selected="c1" showProject />);
    const items = screen.getAllByRole("link");
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining("Waiting one"),
      expect.stringContaining("Busy one"),
    ]);
    expect(items[0]).toHaveAttribute("aria-current", "page");
    expect(items[0].textContent).toContain("PAY · waiting: approve the plan");
    expect(items[0]).toHaveAttribute("href", "/chats/c1");
    rerender(<ChatList chats={chats} selected="c1" showProject={false} />);
    expect(screen.getAllByRole("link")[0].textContent).not.toContain("PAY ·");
  });

  it("says when there are none", () => {
    render(<ChatList chats={[]} showProject />);
    expect(screen.getByText("No chats yet.")).toBeInTheDocument();
  });
});
