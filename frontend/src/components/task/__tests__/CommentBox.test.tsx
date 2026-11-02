import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CommentBox } from "@/components/task/CommentBox";

const users = [
  { id: "11111111-1111-4111-8111-111111111111", name: "Sara Kim" },
  { id: "22222222-2222-4222-8222-222222222222", name: "Sam Lee" },
  { id: "33333333-3333-4333-8333-333333333333", name: "Ahmed Ali" },
];

afterEach(cleanup);

function type(box: HTMLTextAreaElement, value: string) {
  fireEvent.change(box, { target: { value, selectionStart: value.length, selectionEnd: value.length } });
}

describe("CommentBox", () => {
  it("shows a picked mention as @Name, and sends its token", async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(<CommentBox users={users} onSubmit={onSubmit} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    type(box, "Thanks @sa");
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Sara Kim", "Sam Lee"]);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe("Thanks @Sam Lee ");
    expect(screen.queryByRole("listbox")).toBeNull();
    type(box, `${box.value}and @ah`);
    fireEvent.click(screen.getByRole("option", { name: "Ahmed Ali" }));
    expect(box.value).toBe("Thanks @Sam Lee and @Ahmed Ali ");
    type(box, `${box.value}@zz`);
    expect(screen.queryByRole("listbox")).toBeNull(); // no match: no picker
    fireEvent.keyDown(box, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(`Thanks @[Sam Lee](user:${users[1].id}) and @[Ahmed Ali](user:${users[2].id}) @zz`, false),
    );
  });

  it("an email address does not open the picker", () => {
    render(<CommentBox users={users} onSubmit={vi.fn()} />);
    type(screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement, "mail sara@sa");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes on a click outside, without blurring the page", async () => {
    render(<CommentBox users={users} onSubmit={vi.fn()} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    box.focus();
    type(box, "Thanks @sa");
    expect(screen.getByRole("listbox", { name: "Mention someone" })).toBeInTheDocument();
    expect(box).toHaveFocus(); // the cursor stays in the comment
    expect(document.querySelector("[data-backdrop]")).toBeNull();
    await userEvent.click(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Escape closes the list, not the task drawer around it", () => {
    const drawerEscape = vi.fn();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && drawerEscape();
    window.addEventListener("keydown", onKey); // what TaskDrawer listens to
    try {
      render(<CommentBox users={users} onSubmit={vi.fn()} />);
      const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
      type(box, "Thanks @sa");
      fireEvent.keyDown(box, { key: "Escape" });
      expect(screen.queryByRole("listbox")).toBeNull();
      expect(drawerEscape).not.toHaveBeenCalled();
      fireEvent.keyDown(box, { key: "Escape" }); // with no list open, Escape is the drawer's again
      expect(drawerEscape).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener("keydown", onKey);
    }
  });

  it("puts the caret right after a picked mention at once, so fast typing lands after it", () => {
    render(<CommentBox users={users} onSubmit={vi.fn()} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Hi @sa there", selectionStart: 6, selectionEnd: 6 } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe("Hi @Sara Kim  there");
    expect(box.selectionStart).toBe(3 + "@Sara Kim ".length); // not on the next frame: a keystroke may come first
  });

  it("highlights each mention in the box", () => {
    const { container } = render(<CommentBox users={users} onSubmit={vi.fn()} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    type(box, "Thanks @sa");
    fireEvent.keyDown(box, { key: "Enter" });
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["@Sara Kim"]);
    type(box, "Thanks @Sara Ki");
    expect(container.querySelectorAll("mark")).toHaveLength(0); // cut short: plain text again
  });

  it("Backspace right after a mention removes the whole name", () => {
    render(<CommentBox users={users} onSubmit={vi.fn()} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    type(box, "Thanks @sa");
    fireEvent.keyDown(box, { key: "Enter" });
    box.setSelectionRange("Thanks @Sara Kim".length, "Thanks @Sara Kim".length);
    fireEvent.keyDown(box, { key: "Backspace" });
    expect(box.value).toBe("Thanks  ");
  });

  it("a name cut short is sent as plain text", async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(<CommentBox users={users} onSubmit={onSubmit} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    type(box, "Thanks @sa");
    fireEvent.keyDown(box, { key: "Enter" });
    type(box, "Thanks @Sara K");
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Thanks @Sara K", false));
  });

  describe("to the agent", () => {
    const agent = { id: "a1", name: "laptop-claude" };
    const token = "@[laptop-claude](agent:a1)";
    const box = () => screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    const toggle = () => screen.getByRole("switch", { name: "Send to laptop-claude" });

    it("picking the agent in the @ list turns the switch on, and turning it off removes the mention", () => {
      render(<CommentBox users={users} agent={agent} canTellAgent onSubmit={vi.fn()} />);
      type(box(), "@lap");
      const options = screen.getAllByRole("option");
      expect(options[0].textContent).toContain("laptop-claude");
      expect(options[0].textContent).toContain("agent on this task");
      fireEvent.keyDown(box(), { key: "Enter" });
      expect(box().value).toBe("@laptop-claude ");
      expect(toggle()).toHaveAttribute("aria-checked", "true");
      fireEvent.click(toggle());
      expect(toggle()).toHaveAttribute("aria-checked", "false");
      expect(box().value).not.toContain("@laptop-claude");
    });

    it("the switch on its own sends to the agent without a mention", async () => {
      const onSubmit = vi.fn(async () => undefined);
      render(<CommentBox users={users} agent={agent} canTellAgent onSubmit={onSubmit} />);
      fireEvent.click(toggle());
      type(box(), "Use X");
      fireEvent.click(screen.getByRole("button", { name: "Send to agent" }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Use X", true));
    });

    it("deleting the mention turns the switch off unless it was turned on by hand", () => {
      render(<CommentBox users={users} agent={agent} canTellAgent onSubmit={vi.fn()} />);
      type(box(), `${token} use X`);
      expect(toggle()).toHaveAttribute("aria-checked", "true");
      type(box(), "use X");
      expect(toggle()).toHaveAttribute("aria-checked", "false");
      fireEvent.click(toggle());
      type(box(), `${token} use X`);
      type(box(), "use X");
      expect(toggle()).toHaveAttribute("aria-checked", "true");
    });

    it("goes back to an ordinary comment after sending", async () => {
      const onSubmit = vi.fn(async () => undefined);
      render(<CommentBox users={users} agent={agent} canTellAgent onSubmit={onSubmit} />);
      fireEvent.click(toggle());
      type(box(), "Use X");
      fireEvent.click(screen.getByRole("button", { name: "Send to agent" }));
      await waitFor(() => expect(toggle()).toHaveAttribute("aria-checked", "false"));
      expect(screen.getByRole("button", { name: "Comment" })).toBeInTheDocument();
    });

    it("people who can't act see the switch disabled with the reason", () => {
      render(<CommentBox users={users} agent={agent} canTellAgent={false} onSubmit={vi.fn()} />);
      expect(toggle()).toBeDisabled();
      expect(screen.getByText("Only laptop-claude's owner and the project's managers can send it messages.")).toBeInTheDocument();
      type(box(), "@lap");
      expect(screen.queryByRole("option", { name: /laptop-claude/ })).toBeNull();
    });

    it("no agent: switch disabled, agent not in the @ list", () => {
      render(<CommentBox users={users} agent={null} canTellAgent onSubmit={vi.fn()} />);
      expect(screen.getByRole("switch", { name: "Send to the agent" })).toBeDisabled();
      expect(screen.getByText("No agent is assigned to this task.")).toBeInTheDocument();
    });

    it("shows the hint and violet button only while sending to the agent", () => {
      render(<CommentBox users={users} agent={agent} canTellAgent hint="laptop-claude is about to start." onSubmit={vi.fn()} />);
      expect(screen.queryByText("laptop-claude is about to start.")).toBeNull();
      fireEvent.click(toggle());
      expect(screen.getByText("laptop-claude is about to start.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Send to agent" })).toBeInTheDocument();
    });
  });
});
