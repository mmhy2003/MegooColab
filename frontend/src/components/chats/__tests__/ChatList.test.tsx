import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatList } from "@/components/chats/ChatList";
import { chat } from "@/components/chats/__tests__/fixtures";
import { chatGroup, inFilter, intentText, stateText, WAITING, type Chat } from "@/lib/chats";

afterEach(cleanup);


describe("ChatList", () => {
  it("a long title stays inside: two lines, wrapping anywhere", () => {
    render(<ChatList chats={[chat({ title: `see ${"https://git.example.com/a/very/long/path/".repeat(4)}` })]} showProject />);
    const title = screen.getByText(/^see https/);
    // two lines on a phone (no display:block, which would undo the clamp); one line, cut, on a wide screen as before
    expect(title).toHaveClass("max-md:line-clamp-2", "wrap-anywhere", "md:truncate");
    expect(title).not.toHaveClass("block");
  });
});

describe("freestyle chats in the list", () => {
  it("a freestyle row has the chip and says working or waiting for your reply", () => {
    render(<ChatList chats={[
      chat({ id: "f1", title: "Release", mode: "freestyle", state: "working" }),
      chat({ id: "f2", title: "Other", mode: "freestyle", state: "reply" }),
      chat({ id: "w1", title: "Workflow one" }),
    ]} showProject />);
    expect(screen.getAllByText("Freestyle")).toHaveLength(2);
    expect(screen.getByText("working")).toBeInTheDocument();
    expect(screen.getByText("waiting for your reply")).toBeInTheDocument();
  });

  it("the composer line for a turn", () => {
    expect(intentText(chat({ mode: "freestyle", intent: "turn" }), false)).toBe("laptop-claude starts working on your message.");
  });
});

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

  it("merging is not a state that waits on a person", () => {
    expect(WAITING).not.toContain("merging");
  });

  it("names the step, the pull request and the merge", () => {
    const r = chat().rounds[0];
    expect(stateText(chat({ state: "building", rounds: [{ ...r, current_step: 2, steps_total: 3 }] }))).toBe("building step 2 of 3");
    expect(stateText(chat({ state: "human_code_review", rounds: [{ ...r, pr_url: "https://g.io/pull/42" }] }))).toBe("in code review · PR #42");
    expect(stateText(chat({ state: "merging", rounds: [{ ...r, pr_url: "https://g.io/pull/3" }] }))).toBe("merging · PR #3");
    expect(stateText(chat({ state: "merging" }))).toBe("merging");
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
    expect(intentText(chat({ intent: "retry" }), false)).toBe("Retry with your message: laptop-claude starts again and reads it.");
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

describe("a chat's group", () => {
  it.each([
    ["question", "needs_you"], ["design_approval", "needs_you"], ["plan_approval", "needs_you"], ["escalation", "needs_you"],
    ["human_code_review", "needs_you"],
    ["building", "working"], ["in_review", "working"], ["merging", "working"], ["working", "working"],
    ["talking", "open"], ["reply", "open"], ["finished", "open"],
    ["offline", "offline"],
    ["ended", "ended"],
  ] as const)("%s is %s", (state, group) => {
    expect(chatGroup(chat({ state }))).toBe(group);
  });

  it("an ended chat is ended, whatever its last state", () => {
    expect(chatGroup(chat({ state: "building", status: "ended" }))).toBe("ended");
  });

  it("each filter keeps its groups: Active all but ended, Open with offline", () => {
    const of = (state: Chat["state"]) => chat({ state, status: state === "ended" ? "ended" : "open" });
    expect(inFilter(of("ended"), "active")).toBe(false);
    expect(inFilter(of("question"), "active")).toBe(true);
    expect(inFilter(of("offline"), "open")).toBe(true);
    expect(inFilter(of("offline"), "working")).toBe(false);
    expect(inFilter(of("ended"), "all")).toBe(true);
    expect(inFilter(of("building"), "ended")).toBe(false);
  });
});

describe("each row's mark", () => {
  it("starts with its group's mark, the state text in the group's colour, and an ended title dimmed", () => {
    render(<ChatList chats={[
      chat({ id: "a", title: "Asks", state: "question" }),
      chat({ id: "b", title: "Builds", state: "building" }),
      chat({ id: "c", title: "Talks", state: "talking" }),
      chat({ id: "d", title: "Away", state: "offline" }),
      chat({ id: "e", title: "Done", state: "ended", status: "ended" }),
    ]} showProject />);
    const row = (title: string) => screen.getByText(title).closest("a")!;
    expect(row("Asks")).toHaveAttribute("data-group", "needs_you");
    expect(row("Asks").querySelector("[data-mark]")).toHaveClass("bg-amber");
    expect(row("Builds").querySelector("[data-mark]")).toHaveClass("motion-safe:animate-spin");
    expect(row("Talks").querySelector("[data-mark]")).toHaveClass("border-green");
    expect(row("Away").querySelector("[data-mark]")).toHaveClass("bg-pink");
    expect(row("Done").querySelector("[data-mark]")).toHaveClass("bg-line");
    expect(screen.getByText("Done")).toHaveClass("text-muted-foreground");
    expect(screen.getByText(/waiting: answer the agent's question/)).toHaveClass("text-amber");
  });

  it("says when a filter leaves nothing", () => {
    render(<ChatList chats={[]} showProject empty="Nothing needs you." />);
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
  });
});

describe("waiting for another project's answer", () => {
  it("is Working, says whose answer, and marks the row with an hourglass", () => {
    expect(chatGroup(chat({ state: "waiting_answer" }))).toBe("working");
    expect(stateText(chat({ state: "waiting_answer", waiting_on: ["ANS-Q3"] }))).toBe("waiting for ANS's answer");
    expect(stateText(chat({ state: "waiting_answer", waiting_on: ["ANS-Q3", "PAY-Q7"] })))
      .toBe("waiting for answers from ANS and PAY (2)");
    expect(stateText(chat({ state: "waiting_answer", waiting_on: ["ANS-Q3", "ANS-Q4"] })))
      .toBe("waiting for answers from ANS (2)");
    expect(stateText(chat({ state: "waiting_answer" }))).toBe("waiting for another project's answer");
    render(<ChatList chats={[chat({ id: "w", title: "Waits", state: "waiting_answer", waiting_on: ["ANS-Q3"] })]} showProject />);
    const row = screen.getByText("Waits").closest("a")!;
    expect(row).toHaveAttribute("data-group", "working");
    expect(row.querySelector("[data-mark]")).toHaveAttribute("data-hourglass");
    expect(screen.getByText("waiting for ANS's answer")).toHaveClass("text-cyan-ink");
  });

  it("a message now goes with the answers", () => {
    expect(intentText(chat({ state: "waiting_answer", intent: "tell" }), false))
      .toBe("laptop-claude gets this together with the answers it waits for.");
  });
});
