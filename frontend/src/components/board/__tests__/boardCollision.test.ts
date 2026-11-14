import type { ClientRect, CollisionDetection, DroppableContainer, UniqueIdentifier } from "@dnd-kit/core";
import { describe, expect, it } from "vitest";

import { boardCollision } from "../boardCollision";

type Args = Parameters<CollisionDetection>[0];

const rect = (left: number, top: number, width: number, height: number): ClientRect =>
  ({ left, top, width, height, right: left + width, bottom: top + height });

/** Two columns side by side, as tall as the longest: A holds 30 cards (2,500 px), B one card near its top. */
function board() {
  const rects = new Map<UniqueIdentifier, ClientRect>();
  const containers: DroppableContainer[] = [];
  const add = (id: string, r: ClientRect, data: Record<string, unknown>) => {
    rects.set(id, r);
    containers.push({ id, key: id, data: { current: data }, disabled: false, node: { current: null }, rect: { current: r } } as DroppableContainer);
  };
  add("column:A", rect(0, 0, 288, 2_600), { columnId: "A" });
  add("column:B", rect(300, 0, 288, 2_600), { columnId: "B" });
  for (let i = 0; i < 30; i++) add(`A-${i}`, rect(8, 80 + i * 84, 272, 76), { sortable: { containerId: "A" } });
  add("B-0", rect(308, 80, 272, 76), { sortable: { containerId: "B" } });
  add("B-1", rect(308, 164, 272, 76), { sortable: { containerId: "B" } });
  return { rects, containers };
}

function hit(pointer: { x: number; y: number } | null): UniqueIdentifier | undefined {
  const { rects, containers } = board();
  const at = pointer ?? { x: 444, y: 400 };
  const args = {
    active: { id: "A-5" },
    // the dragged card follows the pointer
    collisionRect: rect(at.x - 136, at.y - 38, 272, 76),
    droppableRects: rects,
    droppableContainers: containers,
    pointerCoordinates: pointer,
  } as unknown as Args;
  return boardCollision(args)[0]?.id;
}

describe("boardCollision: the card goes where the pointer is", () => {
  it("drops into a tall column far from its middle, at its end below its cards", () => {
    // far down a column whose own cards are near the top, the old column's cards were nearer: it went back there
    expect(hit({ x: 444, y: 1_000 })).toBe("column:B");
    expect(hit({ x: 444, y: 2_400 })).toBe("column:B");
    expect(hit({ x: 444, y: 400 })).toBe("column:B");
  });

  it("drops onto the card under the pointer", () => {
    expect(hit({ x: 444, y: 100 })).toBe("B-0");
    expect(hit({ x: 444, y: 200 })).toBe("B-1");
  });

  it("between two cards, onto the nearer one", () => {
    expect(hit({ x: 444, y: 158 })).toBe("B-0");
    expect(hit({ x: 444, y: 162 })).toBe("B-1");
  });

  it("over the column's own header, into that column", () => {
    expect(hit({ x: 444, y: 20 })).toBe("B-0");
  });

  it("let go over where it started, onto itself: it stays", () => {
    expect(hit({ x: 144, y: 80 + 5 * 84 + 30 })).toBe("A-5");
  });

  it("with the keyboard (no pointer), as before: the nearest corners", () => {
    expect(hit(null)).toBeDefined();
  });
});
