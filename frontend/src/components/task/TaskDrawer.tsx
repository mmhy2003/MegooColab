"use client";

import { Maximize2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, type CSSProperties } from "react";

import { DrawerResizeHandle } from "./DrawerResizeHandle";
import { DRAWER_DEFAULT_WIDTH, useDrawerWidth } from "./drawerWidth";
import { TaskView } from "./TaskView";
import { Hint } from "@/components/ui/Hint";

export function TaskDrawer({
  taskKey,
  onClose,
  onOpenTask,
}: {
  taskKey: string;
  onClose: () => void;
  onOpenTask: (key: string) => void;
}) {
  useEffect(() => {
    // pickers inside (the @mention and assignee lists) stop their own Escape, so it never gets here
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const panel = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useDrawerWidth();
  // while dragging, only the panel's width changes: the task inside does not render again on every move
  const showWidth = useCallback((w: number) => {
    panel.current?.style.setProperty("--drawer-width", `${w}px`);
  }, []);

  const [projectKey, number] = taskKey.split("-");
  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={taskKey}>
      {/* No close on an outside click: the drawer holds a comment box and editors, so ✕ or Escape closes it */}
      <div data-backdrop aria-hidden className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      {/* from md up: the chosen width, kept between 720 px and the window less 48 px; full width on a phone */}
      <div
        ref={panel}
        style={{ "--drawer-width": `${width}px` } as CSSProperties}
        className="card absolute inset-y-0 right-0 w-full rounded-none border-y-0 border-r-0 md:w-(--drawer-width) md:min-w-[45rem] md:max-w-[calc(100vw-3rem)]"
      >
        <DrawerResizeHandle
          width={width}
          onDrag={showWidth}
          onCommit={setWidth}
          onReset={() => setWidth(DRAWER_DEFAULT_WIDTH)}
        />
        <TaskView
          taskKey={taskKey}
          onOpenTask={onOpenTask}
          onDeleted={onClose}
          headerExtra={
            <>
              <Hint label="Open full page">
                <Link href={`/projects/${projectKey}/tasks/${number}`} className="icon-btn" aria-label="Open full page">
                  <Maximize2 size={16} aria-hidden />
                </Link>
              </Hint>
              <Hint label="Close">
                <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
                  <X size={16} aria-hidden />
                </button>
              </Hint>
            </>
          }
        />
      </div>
    </div>
  );
}
