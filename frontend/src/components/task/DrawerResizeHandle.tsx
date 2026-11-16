"use client";

import { clampDrawerWidth, drawerMaxWidth, DRAWER_MIN_WIDTH, DRAWER_STEP } from "./drawerWidth";
import { Hint } from "@/components/ui/Hint";

/** The drawer's left edge: arrow keys, Home / End to resize, double-click to reset. Shown from md up. */
export function DrawerResizeHandle({
  width,
  onCommit,
  onReset,
}: {
  width: number; // the chosen width, before clamping
  onDrag: (width: number) => void; // live, while dragging: show it without storing it
  onCommit: (width: number) => void;
  onReset: () => void;
}) {
  const now = clampDrawerWidth(width, window.innerWidth);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const next = {
      ArrowLeft: now + DRAWER_STEP, // the edge is on the left: moving it left widens
      ArrowRight: now - DRAWER_STEP,
      Home: DRAWER_MIN_WIDTH,
      End: drawerMaxWidth(window.innerWidth),
    }[e.key];
    if (next === undefined) return; // Escape and the rest go on to the drawer
    e.preventDefault();
    onCommit(clampDrawerWidth(next, window.innerWidth));
  };

  return (
    <Hint label="Drag to resize · double-click to reset">
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize task"
        aria-valuemin={DRAWER_MIN_WIDTH}
        aria-valuemax={drawerMaxWidth(window.innerWidth)}
        aria-valuenow={now}
        tabIndex={0}
        className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none items-center justify-center md:flex"
        onKeyDown={onKeyDown}
        onDoubleClick={onReset}
      >
        <span
          aria-hidden
          className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors group-hover:bg-cyan group-hover:glow-box group-focus-visible:bg-cyan group-focus-visible:glow-box group-data-dragging:bg-cyan group-data-dragging:glow-box"
        />
        <span
          aria-hidden
          className="relative h-8 w-1 rounded-full bg-line transition-[height,background-color] group-hover:h-14 group-hover:bg-cyan group-focus-visible:h-14 group-focus-visible:bg-cyan group-data-dragging:h-14 group-data-dragging:bg-cyan"
        />
      </div>
    </Hint>
  );
}
