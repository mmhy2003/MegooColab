import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ColumnEditor } from "@/components/project/ColumnEditor";
import type { Column } from "@/lib/types";
import { answer } from "@/test/answer";

const COLS: Column[] = [
  { id: "c1", name: "Backlog", position: 0, category: "before", task_count: 0 },
  { id: "c2", name: "In Progress", position: 1, category: "working", task_count: 0 },
  { id: "c3", name: "In Review", position: 2, category: "review", task_count: 2 },
  { id: "c4", name: "Done", position: 3, category: "done", task_count: 0 },
];

function json(status: number, body: unknown) {
  return status === 204
    ? new Response(null, { status })
    : new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("ColumnEditor", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("asks where to move tasks before deleting a non-empty column", async () => {
    vi.mocked(fetch).mockResolvedValue(json(204, null));
    const onChanged = vi.fn();
    render(<ColumnEditor projectKey="PAY" columns={COLS} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete In Review" }));
    const target = await screen.findByLabelText(/move its 2 tasks to/i);
    fireEvent.change(target, { target: { value: "c4" } });
    fireEvent.click(screen.getByRole("button", { name: /delete column/i }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/projects/PAY/columns/c3?move_to=c4");
    expect(init?.method).toBe("DELETE");
  });

  it("explains why the last done column can't go", async () => {
    vi.mocked(fetch).mockResolvedValue(json(409, { detail: "last_before_or_done_column" }));
    render(<ColumnEditor projectKey="PAY" columns={COLS} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Done" }));
    await answer("Delete");
    expect(
      await screen.findByText("A project needs at least one 'before work' column and one 'done' column."),
    ).toBeInTheDocument();
  });

  it("reorders by sending every column id in the new order", async () => {
    vi.mocked(fetch).mockResolvedValue(json(200, []));
    render(<ColumnEditor projectKey="PAY" columns={COLS} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Move Backlog right" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/projects/PAY/columns/order");
    expect(JSON.parse(String(init?.body))).toEqual({ column_ids: ["c2", "c1", "c3", "c4"] });
  });
});
