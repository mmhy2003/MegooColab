# MC-95: the Sound card fits a 280px phone

## Goal
On Settings → Notifications, the Sound card's "Play sound" and "Turn off" / "Turn on" buttons drop below the text when the card is too narrow for both. The page no longer scrolls sideways on a 280px screen, and `e2e/mobile.spec.ts` goes green again.

## Decisions
- **Wrap when the text runs out of room** (chosen by the human, mockup v2). The buttons move below the text as soon as the text would get narrower than 160px. In practice that is screens narrower than about 450px. Wider screens keep today's row.
- **344px changes, on purpose.** The task said 344px should look unchanged, but 344px is already squeezed today: the row needs 282px and the card has 278px inside, so the text is one word per line and the buttons poke 4px into the card's padding. The human chose the roomy layout there too. This replaces the "looks the same at 344px" line of the task's "Done when".
- **No breakpoint.** The layout follows the room the card really has, not the screen width. The Telegram card on the same page already works this way (`TelegramConnect.tsx:39`: `flex flex-wrap` with a `flex-1` text).
- Rejected: **stack below 640px** (`max-sm:flex-col`, as `AddMachine.tsx` does). It stacks on large phones and small tablets where the row still fits.
- Rejected: **stack only below 344px**. It keeps the squeezed text at 344px.
- Rejected: **plain `flex-wrap` on the row with nothing else** (the task's first example). The text's natural width is one long line, so the buttons would wrap on every screen, desktop included. The text needs a small base width for the wrap to happen only when room runs out.

## Architecture
One file changes: `frontend/src/components/notifications/SoundSetting.tsx`, class names only (lines 18, 19 and 27). No markup, text or behaviour changes.

| Element | Today | New |
|---|---|---|
| Outer row (line 18) | `flex items-center justify-between gap-3` | `flex flex-wrap items-center justify-between gap-3` |
| Text block (line 19) | no classes | `min-w-40 flex-1` |
| Button group (line 27) | `flex shrink-0 gap-2` | `flex flex-wrap gap-2` |

How it works:
- `flex-1` gives the text a base width of 0 and `min-w-40` a floor of 160px. The row wraps when 160px + the 12px gap + the buttons (about 213px) no longer fit the card's inside width, so below about 385px inside the card.
- On a shared line the text takes all the room left over and the buttons sit at the right edge, exactly as today. `justify-between` stays, as the task asked; it has no visible effect any more.
- Once wrapped, the text gets the card's full width and the buttons sit below it, left-aligned, 12px lower (`gap-3` applies to both directions).
- The button group loses `shrink-0` and gains `flex-wrap`. At 280px the card has 214px inside and the two buttons need about 213px, which is too close to rely on. If they don't fit (another font, larger text), "Turn off" drops under "Play sound" instead of leaving the card.

Widths, for the plan's checks:

| Screen | Inside the card | Result |
|---|---|---|
| 280px | 214px | buttons below |
| 344px | 278px | buttons below |
| about 451px and wider | 385px and more | row, as today |
| 768px with the sidebar open (the narrowest desktop) | 462px | row, as today |
| wide desktop (card at its 576px maximum) | 542px | row, as today |

## Data and interfaces
None. No props, API, storage or configuration changes.

## Error handling and edge cases
- **Sound off:** the longer text and the primary "Turn on" button use the same layout (shown in the mockup).
- **Buttons wider than the card:** covered by `flex-wrap` on the button group, see above.
- **Browser without Web Audio:** the card is still not rendered at all; unchanged.
- The Push card above has the same row with one button. It fits at 280px and is not touched.

## Testing
- No test changes, as the task says. The existing browser test covers it.
- `megoocolab-runner services run e2e -- npx playwright test e2e/mobile.spec.ts` from `frontend/` passes; in particular `"280 /settings/notifications"` is gone from the problems of "every page fits a phone, 280 and 344 pixels wide".
- `npx vitest run src/components/notifications/__tests__/SoundSetting.test.tsx` still passes (5 tests; they check text and clicks, not classes), then `npx tsc --noEmit` and eslint.
- By eye on Settings → Notifications: buttons below the text at 280px and 344px; a row identical to today at 520px and on desktop; both sound on and sound off.

## Out of scope
- Other cards and other pages.
- The Push card's layout.
- Running browser tests in the release CI.
