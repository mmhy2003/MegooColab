"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { useRef } from "react";

import { useFillWindow } from "./fillWindow";
import { TaskView } from "./TaskView";
import { Hint } from "@/components/ui/Hint";
import { useExpanded } from "@/lib/expanded";

/**
 * A task on its own page: a card down to the window's bottom, so the task scrolls inside it as it does in the drawer
 * and the corner buttons (JumpButtons) stay in view. Expanded (desktop only), it covers the whole window, the menu and
 * the top bar included, as a chat does; the choice is kept in this browser and Esc puts it back.
 */
export function TaskPageCard({
  taskKey,
  onOpenTask,
  onDeleted,
}: {
  taskKey: string;
  onOpenTask: (key: string) => void;
  onDeleted: () => void;
}) {
  const card = useRef<HTMLDivElement | null>(null);
  useFillWindow(card);
  // Esc in the title, the description or a comment leaves it expanded: there it's a key pressed while writing
  const [expanded, setExpanded] = useExpanded("tasks.expanded", { keepTyping: true });
  const label = expanded ? "Collapse task" : "Expand task";
  return (
    // expanded, the height that fills the window gives way (h-auto!, over the inline style) to the whole window
    <div
      ref={card}
      data-task-page
      className={`card ${expanded ? "md:fixed md:inset-0 md:z-40 md:h-auto! md:rounded-none md:border-0" : ""}`}
    >
      <TaskView
        taskKey={taskKey}
        onOpenTask={onOpenTask}
        onDeleted={onDeleted}
        expanded={expanded}
        headerExtra={
          <div className="max-md:hidden">
            <Hint label={expanded ? "Collapse task (Esc)" : "Expand task"}>
              <button type="button" className="icon-btn" aria-label={label} onClick={() => setExpanded(!expanded)}>
                {expanded ? <Minimize2 size={16} aria-hidden /> : <Maximize2 size={16} aria-hidden />}
              </button>
            </Hint>
          </div>
        }
      />
    </div>
  );
}
