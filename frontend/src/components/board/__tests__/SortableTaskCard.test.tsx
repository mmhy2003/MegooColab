import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SortableTaskCard } from "@/components/board/TaskCard";
import type { Task } from "@/lib/types";

const task = {
  id: "t1", key: "PAY-1", title: "Fix login", type: "task", priority: "medium", column_id: "c1", labels: [],
  subtask_count: 0, subtask_done_count: 0, links: [], watcher_ids: [], waiting_on: [], branch_from: null,
} as unknown as Task;

function renderCard(canDrag: boolean) {
  render(
    <DndContext>
      <SortableContext items={["PAY-1"]}>
        <ul><SortableTaskCard task={task} canDrag={canDrag} onOpen={() => {}} /></ul>
      </SortableContext>
    </DndContext>,
  );
  return screen.getByRole("button", { name: "PAY-1 Fix login" });
}

describe("SortableTaskCard", () => {
  it("can be picked up by someone who may change the board", () => {
    expect(renderCard(true)).toHaveAttribute("aria-disabled", "false");
  });

  it("cannot be dragged by a viewer or in a closed project", () => {
    const card = renderCard(false);
    expect(card.className).not.toMatch(/cursor-grab/);
    // still a button that opens the task, but never announced as something to pick up, nor as unavailable
    expect(card).toHaveAttribute("tabindex", "0");
    expect(card).not.toHaveAttribute("aria-roledescription");
    expect(card).not.toHaveAttribute("aria-describedby");
    expect(card).not.toHaveAttribute("aria-disabled");
  });
});
