# MC-24: Notification sound

## Goal

A person who keeps MegooColab open in a browser hears a short two-tone chime when a new notification arrives, so they notice it without watching the bell. They can turn the sound off per browser on Settings → Notifications.

## Decisions

| Question | Answer | Why / what was rejected |
|---|---|---|
| Which notifications chime? | **Every new in-app notification** (whatever raises the bell's count). | The tab already gets a live `notification.created` event for each one, so no backend change. Rejected: a fixed "needs action" list, and a per-kind Sound column (both need the backend to change). |
| When? | **Always while MegooColab is open**, focused or in the background. | Rejected: only when the tab is hidden. |
| The switch | **Per browser, on by default**, kept in `localStorage` like the theme. | Rejected: a per-account setting (migration and API change), and off by default. |
| The sound | **Two-tone chime**, generated with Web Audio: sine 784 Hz then 1175 Hz, about 0.45 s in all, moderate volume. | Picked by ear from four candidates (mockup v1). No audio file to ship or license. |
| Settings card | As in **mockup v2**, including the small print about clicking first. | Approved as shown. |

Agreed along the way:

- With several MegooColab tabs open, **one** of them chimes, not all.
- Notifications that arrive within **2 seconds** of a chime don't chime again (the bell still counts them).

## Architecture

Frontend only. No backend, API or database change.

**`frontend/src/lib/beep.ts`** (new) owns everything about the sound:

- `SOUND_KEY = "notifications.sound"`, and `isSoundOn()`: on unless the stored value is `false` (read with `readStored` from `lib/stored.ts` at the moment of each chime, so a change made in one tab applies to the others at once).
- One lazily created `AudioContext` for the tab (`webkitAudioContext` as fallback).
- `unlockAudio()`: creates the context if needed and resumes it. `useChimeUnlock()` calls it on the tab's first `pointerdown` or `keydown` and then removes its listeners.
- `playChime()`: plays the two notes now. Used by the settings button, whose click is itself the gesture browsers ask for.
- `chimeForNotification()`: the guarded version for live events. It plays only when all of these hold:
  1. the sound is on;
  2. the context exists and is `running` (the tab has been clicked or typed in);
  3. this tab's last chime was more than `CHIME_GAP_MS` (2000) ago;
  4. this tab wins the Web Lock `megoo-chime` (`navigator.locks.request(..., { ifAvailable: true })`), which it then holds for `CHIME_GAP_MS`. That is what makes one tab chime instead of all, and it spreads the 2-second gap across tabs.

**`frontend/src/lib/realtime.ts`**: in `connectRealtime`'s `onmessage`, an event whose type is exactly `notification.created` calls `chimeForNotification()`. Nothing else changes there.

**`frontend/src/app/(app)/layout.tsx`**: calls `useChimeUnlock()` next to `useRealtime()`.

**`frontend/src/components/notifications/SoundSetting.tsx`** (new), rendered in `settings/notifications/page.tsx` directly below `<PushDevices />`. Same card look as the Push card (`card mb-4 max-w-xl p-4 text-sm`), state from `useStoredState(SOUND_KEY, true, "local")`:

- Title: "Sound is on in this browser" / "Sound is off in this browser".
- Line under it: "A short chime plays when a new notification arrives while MegooColab is open." / "Turn it on to hear a short chime when a new notification arrives while MegooColab is open."
- Buttons: **Play sound** (ghost, always works) and **Turn off** (ghost) / **Turn on** (primary).
- Small print under a divider: "Browsers allow sound only after you have clicked or typed in a tab, so a tab you just reloaded stays silent until then."

**Docs**: one sentence in `docs/install.md` section 10 (Notifications), and the browser test's description in `README.md`.

## Data and interfaces

- `localStorage["notifications.sound"]`: `true` or `false` (JSON). Missing means on.
- Web Lock name `megoo-chime`.
- No new endpoint, event, model or config.

## Error handling and edge cases

- **Tab never clicked or typed in since it loaded** (reloaded, restored after a browser restart): silent. The chime is skipped, never queued, so it can't play late at the first click.
- **Notifications that arrived while the socket was disconnected**: no chime. The bell's count still refreshes on reconnect, as today.
- **`notification.read` events** (acting on a task, another tab marking read): no chime.
- **Browser without Web Locks** (an install served over plain http on a non-localhost address): every open tab chimes; the 2-second gap still holds per tab.
- **Browser without Web Audio**: nothing plays and the card isn't shown.
- **Storage blocked** (private window, blocked site data): the sound is on and the switch isn't remembered, as with other stored choices.
- **Tab frozen or discarded by the browser** (memory saver, a phone in the background): it gets no live events, so no chime. Push is the channel for that.
- **Push also on for this device**: the system notification may make its own sound as well. The two are independent switches on the same page.
- Any error from Web Audio or the lock is swallowed: a failed chime never breaks live updates.

## Testing

Tests first, as the repository asks.

- **`lib/__tests__/beep.test.ts`** (Vitest, a fake `AudioContext`, fake timers):
  - on and unlocked: two notes, 784 Hz then 1175 Hz;
  - sound off: nothing;
  - never unlocked: nothing, and still nothing after unlocking later;
  - a second notification within 2 s: nothing; after 2 s: a chime;
  - the lock held by another tab: nothing; no `navigator.locks`: plays;
  - `playChime()` plays even when the sound is off.
- **`lib/__tests__/realtime.test.ts`**: `notification.created` asks for one chime; `notification.read` and `task.updated` ask for none.
- **`components/notifications/__tests__/SoundSetting.test.tsx`**: on by default; Turn off stores `false` and changes the text and button; Turn on stores `true`; Play sound plays.
- **Browser test** (`frontend/e2e/notifications.spec.ts`, fresh `megoo-e2e` stack): an init script swaps `AudioContext` for a recorder. Bea clicks in the page, the admin assigns her a task: the bell shows it and a chime was recorded. She turns the sound off on Settings → Notifications; the next notification raises the bell's count with no new chime.
- Checks: `npx tsc --noEmit`, `npx eslint` on the changed files, `npm test`.

## Out of scope

- Choosing per kind which notifications chime, a choice of sounds, a volume control.
- A per-account setting that follows the person across browsers.
- Sound when MegooColab is closed, or from the push service worker.
- Flashing the tab title or the favicon.
- Getting around the browser's "click first" rule.
