# MC-95 plan: the Sound card fits a 280px phone

## Goal
On Settings → Notifications, the Sound card's buttons move below the text when the card is too narrow for both, so `e2e/mobile.spec.ts` ("every page fits a phone, 280 and 344 pixels wide") passes again.

## Architecture
Only class names change in one component, and nothing else in it: no markup, text or behaviour. The row wraps (`flex-wrap`). The text block gets `flex-1` (base width 0, takes the free room) and `min-w-40` (Tailwind v4: 10rem = 160px floor), so the buttons wrap only when 160px + 12px gap + about 213px of buttons no longer fit. The button group loses `shrink-0` and gains `flex-wrap`, so if the buttons can't fit side by side they wrap inside the card instead of spilling out. This is the same pattern `TelegramConnect.tsx:39-40` already uses.

## File map
| File | Change |
|---|---|
| `frontend/src/components/notifications/SoundSetting.tsx` | class names on lines 18, 19 and 27 |

No test files change. The existing `frontend/e2e/mobile.spec.ts:98` and `frontend/src/components/notifications/__tests__/SoundSetting.test.tsx` cover it.

## Steps

### 1. Let the Sound card's buttons wrap below the text on narrow cards
The "failing test" is the existing browser test. No new test is written, as the task and design say.

1. Confirm it fails first. From `frontend/`:
   `megoocolab-runner services run e2e -- npx playwright test e2e/mobile.spec.ts`
   Expected: "every page fits a phone, 280 and 344 pixels wide" fails, and the problems include `"280 /settings/notifications": ["div.flex shrink-0 gap-2 → 315px"]`. Other pages may fail too. Write down any of them: they are out of scope and must not be "fixed" here.
2. Edit `frontend/src/components/notifications/SoundSetting.tsx`:
   - line 18: `<div className="flex items-center justify-between gap-3">` → `<div className="flex flex-wrap items-center justify-between gap-3">`
   - line 19: `<div>` → `<div className="min-w-40 flex-1">`
   - line 27: `<div className="flex shrink-0 gap-2">` → `<div className="flex flex-wrap gap-2">`
   Change nothing else: not the text, not the Buttons, not the outer `section`.

   Result (lines 18-33):
   ```tsx
         <div className="flex flex-wrap items-center justify-between gap-3">
           <div className="min-w-40 flex-1">
             <p className="font-semibold">{on ? "Sound is on in this browser" : "Sound is off in this browser"}</p>
             <p className="text-xs text-muted-foreground">
               {on
                 ? "A short chime plays when a new notification arrives while MegooColab is open."
                 : "Turn it on to hear a short chime when a new notification arrives while MegooColab is open."}
             </p>
           </div>
           <div className="flex flex-wrap gap-2">
             <Button variant="ghost" onClick={playChime}>Play sound</Button>
             <Button variant={on ? "ghost" : "primary"} onClick={() => setOn(!on)}>
               {on ? "Turn off" : "Turn on"}
             </Button>
           </div>
         </div>
   ```
3. From `frontend/`, run in order:
   - `npx vitest run src/components/notifications/__tests__/SoundSetting.test.tsx`: 5 tests pass.
   - `npx tsc --noEmit`: no errors.
   - `npx eslint src/components/notifications/SoundSetting.tsx`: no problems.
   - `megoocolab-runner services run e2e -- npx playwright test e2e/mobile.spec.ts`: passes; `280 /settings/notifications` no longer appears among the problems. If the test still fails only because of pages noted in point 1, report them and don't change them.
4. Check by eye on Settings → Notifications, with sound on and sound off:
   - 280px and 344px: buttons below the text, left-aligned, no sideways scroll.
   - 520px, 768px with the sidebar open, and wide desktop: one row, the same as today, text on the left and buttons on the right.
5. Commit, with no `.megoocolab/` or `docs/` files:
   ```
   fix(notifications): wrap the Sound card's buttons on narrow screens (MC-95)

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   ```

## Final verification
From `frontend/`:
```sh
npx vitest run src/components/notifications/__tests__/SoundSetting.test.tsx
npx tsc --noEmit
npx eslint src/components/notifications/SoundSetting.tsx
megoocolab-runner services run e2e -- npx playwright test e2e/mobile.spec.ts
git diff main --stat   # only frontend/src/components/notifications/SoundSetting.tsx
```
Then the visual check from step 1, point 4.
