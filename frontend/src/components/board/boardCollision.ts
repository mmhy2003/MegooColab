import { closestCorners, pointerWithin, type CollisionDetection, type DroppableContainer } from "@dnd-kit/core";

const columnOf = (d: DroppableContainer): string | undefined => d.data.current?.sortable?.containerId;

/**
 * Where a dragged card lands: in the column under the pointer, wherever in that column the pointer is. Corner
 * distances alone (dnd-kit's closestCorners) measure a tall column from its far top and bottom corners, so the cards
 * of the column it came from won unless the card was held near the tall column's middle.
 *
 * Over a card: that card. Between cards: the one whose middle is nearest. Below the column's last card (or in an
 * empty column): the column, which puts the card at its end. With no pointer (the keyboard), the nearest corners.
 */
export const boardCollision: CollisionDetection = (args) => {
  const pointer = args.pointerCoordinates;
  if (!pointer) return closestCorners(args);
  const column = pointerWithin(args).find((c) => String(c.id).startsWith("column:"));
  if (!column) return closestCorners(args);
  const columnId = String(column.id).slice("column:".length);
  const cards = args.droppableContainers
    .filter((d) => columnOf(d) === columnId) // the dragged card too: let go where it was, it stays
    .map((d) => ({ id: d.id, rect: args.droppableRects.get(d.id) }))
    .filter((c): c is { id: DroppableContainer["id"]; rect: NonNullable<typeof c.rect> } => c.rect != null);
  const last = Math.max(...cards.map((c) => c.rect.bottom));
  if (cards.length === 0 || pointer.y > last) return [column];
  const nearest = cards.reduce((best, c) => {
    const d = Math.abs(c.rect.top + c.rect.height / 2 - pointer.y);
    return d < best.d ? { id: c.id, d } : best;
  }, { id: cards[0].id, d: Infinity });
  return [{ id: nearest.id, data: { droppableContainer: args.droppableContainers.find((d) => d.id === nearest.id) } }];
};
