/**
 * Neighbours for a card dropped at `overIndex` in a column (its final index once dropped).
 * `before_key` is the card that ends up directly above it, `after_key` the one directly below.
 */
export function moveTarget(
  columnTasks: { key: string }[],
  overIndex: number,
  draggedKey: string,
): { before_key?: string; after_key?: string } {
  const others = columnTasks.filter((t) => t.key !== draggedKey);
  const i = Math.max(0, Math.min(overIndex, others.length));
  const out: { before_key?: string; after_key?: string } = {};
  if (i > 0) out.before_key = others[i - 1].key;
  if (i < others.length) out.after_key = others[i].key;
  return out;
}
