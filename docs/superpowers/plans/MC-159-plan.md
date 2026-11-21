# MC-159 implementation plan: two-line rows in the Dashboard's Chats card

## Goal
On every screen width, each chat in the Dashboard's Chats card shows the project key, then the title, and below them the status.

## Architecture
The change is in one component, `frontend/src/components/dashboard/ChatsCard.tsx`, and only in the `<li>` it draws for each chat. Line 1 is a single `Link` to `/chats/{id}` that holds a monospace cyan key (never cut) and the title (cut with "…"). Line 2 is a `<p>` with the status text from `chatStateText`, in the same colour as today. The long status wraps instead of being cut. There is no backend, API or type change.

## Conventions
- Work on the current branch `megoo/MC-159-improve-dashboard-mobile-ui`. Make one commit. The body explains why and what in plain sentences and ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- Frontend checks: `cd frontend; npx tsc --noEmit; npx eslint <changed files>; npm test`. Don't run Prettier.

## File map
| File | Change |
|---|---|
| `frontend/src/components/dashboard/ChatsCard.tsx` | Modify: the chat `<li>` becomes two lines. |
| `frontend/src/components/dashboard/__tests__/ChatsCard.test.tsx` | Modify: replace the "capped" test and update "lists open chats…". |

`frontend/e2e/chats.spec.ts` stays as it is. It calls `getByText("Fix the empty email crash")` inside the Chats region. The title is now a span of its own, so the exact text still matches.

## Steps

### 1. Chats card: key and title on line 1, status below (MC-159)

**Files:** `frontend/src/components/dashboard/__tests__/ChatsCard.test.tsx`, `frontend/src/components/dashboard/ChatsCard.tsx`.

**1a. Write the failing tests first.** In `ChatsCard.test.tsx`, replace the test `"the status side is capped so the name keeps its room"` with:

```tsx
  it("puts the status on its own line, outside the link and never cut", () => {
    render(<ChatsCard chats={[brief()]} />);
    const status = screen.getByText("waiting: approve the plan");
    expect(status).not.toHaveClass("max-w-[45%]");
    expect(status).not.toHaveClass("truncate");
    expect(status).toHaveClass("break-words", "text-amber");
    expect(status.closest("a")).toBeNull();
  });
```

Then replace the body of `"lists open chats with what each is doing, and links to all chats and a new one"` with:

```tsx
    render(<ChatsCard chats={[brief(), brief({ id: "c2", title: "Bump axios", project_key: "WEB", state: "building", current_step: 2, steps_total: 3 })]} />);
    const card = screen.getByRole("region", { name: "Chats" });
    const items = within(card).getAllByRole("listitem");
    const link = within(card).getByRole("link", { name: "PAY Fix empty email" });
    expect(link).toHaveAttribute("href", "/chats/c1");
    const key = within(items[0]).getByText("PAY");
    const title = within(items[0]).getByText("Fix empty email");
    const status = within(items[0]).getByText("waiting: approve the plan");
    expect(key).toHaveClass("font-mono", "shrink-0", "text-cyan-ink");
    expect(title).toHaveClass("truncate");
    expect(link).toContainElement(key);
    expect(link).toContainElement(title);
    // order inside the row: key, then title, then status
    expect(key.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(title.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(items[1].textContent).toContain("building step 2 of 3");
    expect(within(card).getByRole("link", { name: "WEB Bump axios" })).toHaveAttribute("href", "/chats/c2");
    expect(within(card).getByRole("link", { name: "New chat" })).toHaveAttribute("href", "/chats?new=1");
    expect(within(card).getByRole("link", { name: /^All chats/ })).toHaveAttribute("href", "/chats");
```

Leave `"says when there are none"` and the `FinishedChart` block as they are.

Run: `cd frontend; npx vitest run src/components/dashboard/__tests__/ChatsCard.test.tsx`. Expect the two changed tests to fail. Today the status span has `max-w-[45%] truncate`, and the link's name is "Fix empty email · PAY".

**1b. Implement.** In `ChatsCard.tsx`, replace the `return ( <li …> … </li> );` inside `chats.map`. Keep the `state` and `tone` lines exactly as they are.

```tsx
            return (
              <li key={c.id} className="space-y-0.5 py-1.5 text-sm">
                <Link href={`/chats/${c.id}`} className="group flex min-w-0 items-center gap-1.5 text-fg no-underline">
                  <span className="shrink-0 font-mono text-xs text-cyan-ink">{c.project_key}</span>{" "}
                  <span className="min-w-0 truncate group-hover:underline">{c.title}</span>
                </Link>
                <p className={`text-xs break-words ${tone}`}>{chatStateText({ ...c, state })}</p>
              </li>
            );
```

The `{" "}` between the two spans makes the link's accessible name "PAY Fix empty email" and not "PAYFix empty email". In a flex container a text node that holds only whitespace is not drawn, so `gap-1.5` alone sets the spacing. Change nothing else in the file: the heading, "New chat", "All chats", the empty text and the order stay.

Run again: `cd frontend; npx vitest run src/components/dashboard/__tests__/ChatsCard.test.tsx`. Expect all tests to pass.

**1c. Checks.** Run `cd frontend; npx tsc --noEmit; npx eslint src/components/dashboard/ChatsCard.tsx src/components/dashboard/__tests__/ChatsCard.test.tsx; npm test`. All must be clean or green.

**1d. Commit.** Subject: `feat(dashboard): two-line chat rows, key first (MC-159)`. Body: on a phone the one-line row cut both the title and the status, and it hid the project key. Each row now shows the key and the title as one link, with the status on its own line, at every width, as Running now does.

## Final verification
- `cd frontend; npx tsc --noEmit`
- `cd frontend; npx eslint src/components/dashboard/ChatsCard.tsx src/components/dashboard/__tests__/ChatsCard.test.tsx`
- `cd frontend; npm test`
- Optionally `megoocolab-runner services run e2e -- npx playwright test e2e/chats.spec.ts` (from `frontend/`). The Chats-region title lookup still matches.
- By hand at 375px and on desktop, the Dashboard shows:
  - the key in cyan monospace, then the title, cut with "…" when long;
  - the status below, wrapping when long (the offline text);
  - the whole first line opening the chat, with the title underlined on hover.
