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
  it("inserts a mention token from the picker", async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(<CommentBox users={users} onSubmit={onSubmit} />);
    const box = screen.getByRole("textbox", { name: "Add a comment" }) as HTMLTextAreaElement;
    type(box, "Thanks @sa");
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Sara Kim", "Sam Lee"]);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe(`Thanks @[Sam Lee](user:${users[1].id}) `);
    expect(screen.queryByRole("listbox")).toBeNull();
    type(box, `${box.value}and @ah`);
    fireEvent.click(screen.getByRole("option", { name: "Ahmed Ali" }));
    expect(box.value).toBe(`Thanks @[Sam Lee](user:${users[1].id}) and @[Ahmed Ali](user:${users[2].id}) `);
    type(box, `${box.value}@zz`);
    expect(screen.queryByRole("listbox")).toBeNull(); // no match: no picker
    fireEvent.keyDown(box, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.stringContaining(`@[Ahmed Ali](user:${users[2].id})`)));
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
});
