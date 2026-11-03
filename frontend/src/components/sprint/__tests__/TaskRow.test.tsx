import { DndContext } from "@dnd-kit/core";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskRow } from "@/components/sprint/SprintPanel";
import type { Task } from "@/lib/types";

afterEach(cleanup);

const task = { key: "PAY-1", title: "A task with a rather long title that must wrap", type: "task", column_category: "todo", story_points: null } as unknown as Task;

describe("TaskRow", () => {
  it("the backlog row's controls are tap-sized and the title takes the row on phones", () => {
    render(
      <DndContext>
        <ul>
          <TaskRow task={task} destinations={[{ id: "s1", name: "Sprint 1" }]} disabled={false} onOpen={vi.fn()} onMove={vi.fn()} />
        </ul>
      </DndContext>,
    );
    expect(screen.getByRole("button", { name: "Drag PAY-1" })).toHaveClass("min-h-8", "min-w-8");
    expect(screen.getByRole("combobox", { name: "Move PAY-1 to" })).toHaveClass("min-h-8");
    expect(screen.getByRole("button", { name: /A task with a rather long title/ })).toHaveClass("max-sm:basis-full");
  });
});
