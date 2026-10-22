import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BacklogQuickCreate } from "@/components/sprint/BacklogQuickCreate";

describe("BacklogQuickCreate", () => {
  it("creates backlog items of any type, epics included", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<BacklogQuickCreate onCreate={onCreate} />);
    const type = screen.getByLabelText("New item type") as HTMLSelectElement;
    expect([...type.options].map((o) => o.value)).toEqual(["story", "task", "bug", "epic"]);
    fireEvent.change(type, { target: { value: "epic" } });
    fireEvent.change(screen.getByLabelText("New backlog item"), { target: { value: "Checkout revamp" } });
    fireEvent.submit(screen.getByLabelText("New backlog item").closest("form")!);
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith("Checkout revamp", "epic"));
    expect((screen.getByLabelText("New backlog item") as HTMLInputElement).value).toBe("");
  });
});
