import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskTitle } from "@/components/task/TaskTitle";

afterEach(cleanup);

const LONG = "A task with a rather long title that must wrap on a narrow phone screen";

describe("TaskTitle", () => {
  it("wraps a long title over several lines instead of cutting it", () => {
    render(<TaskTitle value={LONG} onSave={() => {}} />);
    const title = screen.getByRole("textbox", { name: "Title" });
    expect(title.tagName).toBe("TEXTAREA");
    expect(title).toHaveValue(LONG);
  });

  it("saves on Enter without adding a line break", () => {
    const onSave = vi.fn();
    render(<TaskTitle value="Old" onSave={onSave} />);
    const title = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(title, { target: { value: "  New title  " } });
    const enter = fireEvent.keyDown(title, { key: "Enter" });
    expect(enter).toBe(false); // the line break was prevented
    fireEvent.blur(title);
    expect(onSave).toHaveBeenCalledExactlyOnceWith("New title");
  });

  it("saves nothing when the title is unchanged or emptied", () => {
    const onSave = vi.fn();
    render(<TaskTitle value="Same" onSave={onSave} />);
    const title = screen.getByRole("textbox", { name: "Title" });
    fireEvent.blur(title);
    fireEvent.change(title, { target: { value: "   " } });
    fireEvent.blur(title);
    expect(onSave).not.toHaveBeenCalled();
  });
});
