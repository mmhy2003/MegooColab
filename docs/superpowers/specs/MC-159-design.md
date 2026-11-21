# MC-159: two-line rows in the Dashboard's Chats card

This design goes with mockup **v2** ("Final: Chats card, layout B at every width (phone and desktop)").

## Goal

Each chat in the Dashboard's Chats card shows the project key first (as the link to the chat), then the title, then the status on its own line. Today the row is one line, `title · KEY` then the status, and on a phone the title and the status cut each other short and the project key is usually hidden.

## Decisions

| Question | Answer | Rejected |
|---|---|---|
| Row layout | **B: two lines.** Line 1 is the project key and the title. Line 2 is the status in its colour. (Chosen by the human.) | A: the same as Running now, with a state dot, the agent's name and a status chip. C: one line with a short status chip, which needs new short status wording. |
| Which widths | **Every width**, as Running now does. (Chosen by the human.) | Phone only, with the single line kept from 768px up. |

Decisions I made, for you to confirm by approving:

1. **The whole first line is one link to the chat.** Only the key is coloured as a link (cyan, monospace, like a task key in Running now and My tasks). The title keeps the text colour and is underlined on hover. If only the key were the link, the tap target on a phone would be two or three letters.
2. **A long title is cut with "…". The key is never cut.**
3. **A long status wraps to a second line and is never cut.** The status now has the full width, so only the offline text ("offline — starts when …'s runner connects") wraps on a phone. The `max-w-[45%]` cap goes away.
4. **Status colours and wording do not change.** Amber for the waiting states (`WAITING`), cyan for building and in review, grey otherwise. The text still comes from `chatStateText`.
5. **The rest of the card does not change**: the heading, "All chats →", "New chat", the empty text, and which chats are listed and in what order.

## Architecture

The change is in one component, `frontend/src/components/dashboard/ChatsCard.tsx`. Only the `<li>` of a chat changes:

- The `<li>` becomes a block with `space-y-0.5 py-1.5 text-sm`, the same row spacing as `RunningNow.tsx`.
- **Line 1** is a `Link` to `/chats/{id}` with `flex min-w-0 items-center gap-1.5 text-fg no-underline`, and `group` so the title can react to hover. It contains:
  - the key: `<span className="shrink-0 font-mono text-xs text-cyan-ink">{c.project_key}</span>`
  - the title: `<span className="min-w-0 truncate group-hover:underline">{c.title}</span>`
- **Line 2** is the status: `<p className={`text-xs break-words ${tone}`}>{chatStateText({ ...c, state })}</p>`. The `tone` computation stays as it is.

`RunLink` is not reused. It draws a chat as a "chat" tag plus the title, and it takes a `RunningItem`, not a `ChatBrief`. The key's look is two classes that `MyTasks.tsx` and `NeedsYou.tsx` also write inline.

## Data and interfaces

None. `ChatBrief` already carries `id`, `title`, `project_key` and the fields `chatStateText` reads. No backend, API or generated-type change (`api-types.ts` is not regenerated).

## Error handling and edge cases

- **Long title**: cut with "…" on line 1. The key stays whole (`shrink-0`).
- **Long status**: wraps (`break-words`), so that row is three lines high. Nothing overflows the card.
- **No chats**: "No open chats.", as today.
- **Accessible name of the link**: the key then the title, for example "PAY Fix empty email" (two spans in one link).

## Testing

Update `frontend/src/components/dashboard/__tests__/ChatsCard.test.tsx` (Vitest and Testing Library), test first:

- Replace "the status side is capped…" with: the status has no `max-w-[45%]` and no `truncate` class, and it is not inside the link.
- In "lists open chats…": the link's name is `PAY Fix empty email` and its `href` is `/chats/c1`. Inside the row the order is key, title, status. The key element has `font-mono` and `shrink-0`, and the title element has `truncate`. The "New chat" and "All chats" assertions stay.
- "says when there are none" stays as it is.

Checks: `cd frontend; npx tsc --noEmit; npx eslint src/components/dashboard/ChatsCard.tsx src/components/dashboard/__tests__/ChatsCard.test.tsx; npm test`. The end-to-end test `frontend/e2e/chats.spec.ts` looks for the chat's title as text inside the Chats region. That still matches, so it needs no change.

## Out of scope

- The agent's name, a state dot or a time on the row (option A).
- New short status wording (option C).
- Other Dashboard cards, and the Chats page's own list.
- Any backend change.
