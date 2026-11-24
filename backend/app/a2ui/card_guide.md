# Cards in show_card

A card shows a result in the thread of your task or chat, next to your reply: headline numbers, tabs, and lists
with links to tasks. It is read-only and a snapshot: it never updates. Cards use the A2UI v1.0 format with
MegooColab's catalog, which is in `catalog` next to this text.

## When

Only when a result reads better as tiles, tabs or a list of task links than as Markdown. Your Markdown reply
already has tables, links and Mermaid. Always reply in text as well.

## What you send

`show_card(key, title, text, card)`:
- `title` (1 to 120 characters) is the card's heading.
- `text` (1 to 500 characters) stands in for the card wherever it can't be drawn: notifications, search, and
  the prompts of other agents. Write it as a full, short summary of the card.
- `card` is `{"components": [...], "data": {...}}`. MegooColab adds the surface id, the catalog id and the envelope.

- `components` is a flat list. Each has a unique `id` and a `component` name; containers name children by id.
- The component with `"id": "root"` is the top. Every other component must be reachable from it.
- `data` (optional) is the data model that bound values read from (`{"@path": "/name"}`).

## Components

Layout:
- `Column`, `Row`: arrange their `children` top to bottom, or side by side.
- `Card`: a box around its single `child`.
- `Divider`: a line.
- `Text`: a short text with simple Markdown; Markdown links work.

Display:
- `Tabs`: up to 6 `tabs`, each `{title, child}`. The first is open.
- `List`: rows with a line between them. `children` is a list of ids, or a template
  `{"componentId": "<id>", "path": "/<array>"}` drawn once per item of that array, with paths inside the
  template relative to the item (`{"@path": "key"}`).
- `StatTile`: a `value` with its `label`, an optional `caption`, and a `tone`: `neutral`, `good`, `warning` or `bad`.
- `TaskLink`: a link to a task by its key (`task`, such as `MC-181`), followed by `label`. The label is your words,
  not the task's current title.

There are no inputs, buttons, images or media in a card.

## Limits

- At most 16 KB of card JSON and 60 components.
- At most 6 tabs in one `Tabs`, and 50 items in any array of `data`.
- At most 3 cards in one run, and 100 on one task.

Refusals: `invalid_card` followed by up to 10 `path: message` lines (it doesn't match the catalog, an empty title
or text, or a `TaskLink` whose literal `task` is not a task key), `card_with_inputs`, `too_large`, `too_many_cards`.
Nothing was stored: fix the card and call `show_card` again.

`example` next to this text is a complete card you can start from.
