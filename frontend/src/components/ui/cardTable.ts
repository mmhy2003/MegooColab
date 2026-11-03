/** A data table that becomes a stack of cards on a phone, rather than scrolling sideways: the header row hides, each
 * row is a card and each cell shows its column's name (`data-label`) before its value. Wide screens keep the table. */
export const CARD_TABLE = {
  table: "max-md:block",
  thead: "max-md:hidden",
  tbody: "max-md:block max-md:space-y-2",
  tr: "max-md:block max-md:rounded max-md:border max-md:border-line max-md:bg-surface max-md:p-3",
  // a cell: its label, then its value, on one line
  td: "max-md:flex max-md:gap-2 max-md:px-0 max-md:py-0.5 max-md:before:w-24 max-md:before:shrink-0 max-md:before:text-xs max-md:before:text-muted-foreground max-md:before:content-[attr(data-label)]",
  // the box around it: a card on a wide screen, nothing on a phone (each row is a card)
  box: "card max-md:border-0 max-md:bg-transparent max-md:shadow-none",
} as const;
