# MC-24 plan: notification chime

## Goal

When a new in-app notification arrives, an open MegooColab tab plays a short two-tone chime (784 Hz, then 1175 Hz). Only one tab chimes, and a burst of notifications gives one chime. People can turn the sound off for their browser on Settings → Notifications.

## Architecture

The change is frontend only. A new module, `frontend/src/lib/beep.ts`, owns the sound: the per-browser switch, one lazily created `AudioContext`, the unlock on the first click or key, the chime itself, and the guarded version for live events (the 2 s gap and the Web Lock `megoo-chime`). `connectRealtime` calls `chimeForNotification()` on `notification.created`. The app layout calls `useChimeUnlock()`. A new `SoundSetting` card sits under `<PushDevices />`.

## File map

| File | Change | What it does |
|---|---|---|
| `frontend/src/lib/beep.ts` | new | `SOUND_KEY`, `CHIME_GAP_MS`, `audioSupported`, `isSoundOn`, `unlockAudio`, `playChime`, `chimeForNotification`, `listenForUnlock`, `useChimeUnlock` |
| `frontend/src/lib/__tests__/beep.test.ts` | new | Vitest with a fake `AudioContext` and fake timers |
| `frontend/src/lib/realtime.ts` | modify | One line in `onmessage` |
| `frontend/src/lib/__tests__/realtime.test.ts` | modify | Mocks `@/lib/beep`, adds a chime test |
| `frontend/src/app/(app)/layout.tsx` | modify | `useChimeUnlock()` next to `useRealtime()` |
| `frontend/src/components/notifications/SoundSetting.tsx` | new | The settings card |
| `frontend/src/components/notifications/__tests__/SoundSetting.test.tsx` | new | Component tests |
| `frontend/src/app/(app)/settings/notifications/page.tsx` | modify | Renders `<SoundSetting />` under `<PushDevices />` |
| `frontend/e2e/notifications.spec.ts` | modify | Adds part 6: the chime, then silence once the sound is off |
| `docs/install.md` (section 10), `README.md` (line ~151) | modify | One sentence each |

Every command below runs from `frontend/`.

## Reference code

### A. `frontend/src/lib/beep.ts`

```ts
"use client";

import { useEffect } from "react";

import { readStored } from "@/lib/stored";

/** localStorage key of the per-browser switch: true or false (JSON); missing means on. */
export const SOUND_KEY = "notifications.sound";
/** No second chime within this long of the last one: in this tab, and in the others through the lock. */
export const CHIME_GAP_MS = 2_000;
const LOCK = "megoo-chime";
const VOLUME = 0.15;
// the two-tone chime: 784 Hz then 1175 Hz, about 0.45 s in all
const NOTES = [
  { freq: 784, at: 0, dur: 0.25 },
  { freq: 1175, at: 0.15, dur: 0.3 },
];

let ctx: AudioContext | null = null;
let lastChime = -Infinity;

function audioClass(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
}

/** Whether this browser can play the chime at all (Web Audio). */
export function audioSupported(): boolean {
  return audioClass() !== undefined;
}

/** On unless this browser stored false; read at each chime, so a change in another tab applies at once. */
export function isSoundOn(): boolean {
  return readStored<boolean>(SOUND_KEY, "local") !== false;
}

/** Creates the tab's audio context if needed and resumes it; browsers allow it only after a click or a key. */
export function unlockAudio(): void {
  try {
    if (!ctx) {
      const AC = audioClass();
      if (!AC) return;
      ctx = new AC();
    }
    if (ctx.state === "suspended") void ctx.resume().catch(() => {});
  } catch {
    ctx = null;
  }
}

function play(c: AudioContext): void {
  const t0 = c.currentTime;
  for (const note of NOTES) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    const start = t0 + note.at;
    osc.type = "sine";
    osc.frequency.value = note.freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(VOLUME, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + note.dur);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(start);
    osc.stop(start + note.dur);
  }
}

/** Plays the chime now, whatever the switch says: the settings button's click is itself the gesture browsers ask for. */
export function playChime(): void {
  unlockAudio();
  try {
    if (ctx) play(ctx);
  } catch {
    // nothing plays; the page still works
  }
}

/** The chime for a live notification. It plays only when the sound is on, the tab is unlocked, the last chime was
 *  CHIME_GAP_MS or more ago, and this tab wins the lock (held for CHIME_GAP_MS, so one tab chimes, not all). It is
 *  skipped, never queued. */
export function chimeForNotification(): void {
  try {
    const c = ctx;
    if (!isSoundOn() || !c || c.state !== "running") return;
    const now = Date.now();
    if (now - lastChime < CHIME_GAP_MS) return;
    lastChime = now;
    // no Web Locks (plain http away from localhost): every tab chimes, each keeping its own gap
    if (!("locks" in navigator) || !navigator.locks) {
      play(c);
      return;
    }
    void navigator.locks
      .request(LOCK, { ifAvailable: true }, async (lock) => {
        if (!lock) return; // another tab is chiming
        play(c);
        await new Promise((resolve) => setTimeout(resolve, CHIME_GAP_MS));
      })
      .catch(() => {});
  } catch {
    // a failed chime never breaks live updates
  }
}

/** Unlocks audio on the tab's first click or key; stops listening once the context runs. Returns the cleanup. */
export function listenForUnlock(): () => void {
  const stop = () => {
    window.removeEventListener("pointerdown", unlock, true);
    window.removeEventListener("keydown", unlock, true);
  };
  function unlock() {
    unlockAudio();
    if (ctx?.state === "running") stop();
  }
  window.addEventListener("pointerdown", unlock, true);
  window.addEventListener("keydown", unlock, true);
  return stop;
}

export function useChimeUnlock(): void {
  useEffect(listenForUnlock, []);
}
```

### B. `frontend/src/lib/__tests__/beep.test.ts`

The module keeps its state (`ctx`, `lastChime`) across calls, so every test loads a fresh copy with `vi.resetModules()` and a dynamic import. No React hook is rendered here: the hook is tested through `listenForUnlock`.

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

class FakeContext {
  static instances: FakeContext[] = [];
  state: AudioContextState = "suspended";
  currentTime = 0;
  destination = {};
  played: number[] = [];
  resume = vi.fn(async () => {
    this.state = "running";
  });
  constructor() {
    FakeContext.instances.push(this);
  }
  createGain() {
    return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} };
  }
  createOscillator() {
    const osc = { type: "", frequency: { value: 0 }, connect() {}, start: () => this.played.push(osc.frequency.value), stop() {} };
    return osc;
  }
}

async function fresh() {
  vi.resetModules();
  return import("@/lib/beep");
}
const played = () => FakeContext.instances.flatMap((c) => c.played);

function stubLocks(held: boolean) {
  const request = vi.fn((_name: string, _opts: object, cb: (lock: object | null) => unknown) => Promise.resolve(cb(held ? null : { name: "megoo-chime" })));
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request } });
  return request;
}

beforeEach(() => {
  FakeContext.instances = [];
  vi.stubGlobal("AudioContext", FakeContext);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
  delete (navigator as { locks?: unknown }).locks;
});
```

The tests, each starting with `const beep = await fresh();`:

- `describe("chimeForNotification")`:
  - "plays two notes, 784 Hz then 1175 Hz, when on and unlocked": `beep.unlockAudio(); beep.chimeForNotification();` gives `played()` equal to `[784, 1175]`.
  - "stays silent when the sound is off": `localStorage.setItem("notifications.sound", "false")`, then unlock and chime: `[]`.
  - "stays silent in a tab never clicked, and does not play late once unlocked": chime, then `unlockAudio()`: `[]`.
  - "chimes once for a burst, and again after 2 s": unlock, chime (2 notes), `vi.advanceTimersByTime(1999)`, chime (still 2), `vi.advanceTimersByTime(1)`, chime (4).
  - "stays silent when another tab holds the lock": `stubLocks(true)`: `[]`, and `request` was called with `("megoo-chime", { ifAvailable: true }, expect.any(Function))`.
  - "plays when it wins the lock": `stubLocks(false)`: `[784, 1175]`.
  - "plays without Web Locks": no stub (jsdom has no `navigator.locks`): `[784, 1175]`.
- `describe("playChime")`: "plays even when the sound is off, without an earlier click": stored `false`, then `beep.playChime()`: `[784, 1175]`.
- `describe("isSoundOn")`: on with nothing stored, on with `true`, off with `false`.
- `describe("audioSupported")`: true with the stub, false after `vi.unstubAllGlobals()` (jsdom has no `AudioContext`).
- `describe("listenForUnlock")`:
  - "unlocks on the first pointerdown, then stops listening": `const stop = beep.listenForUnlock(); window.dispatchEvent(new Event("pointerdown"));` gives one instance with state `running`. A second `pointerdown` and a `keydown` still leave `resume` called once. Call `stop()` at the end.
  - "unlocks on a key": a `keydown` gives state `running`.
  - "the cleanup removes the listeners": `stop()` then `pointerdown`: no instance.

### C. `frontend/src/components/notifications/SoundSetting.tsx`

```tsx
"use client";

import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/Button";
import { audioSupported, playChime, SOUND_KEY } from "@/lib/beep";
import { useStoredState } from "@/lib/stored";

const noChanges = () => () => undefined;

/** The per-browser switch for the chime played when a new notification arrives, with a button to hear it. */
export function SoundSetting() {
  const supported = useSyncExternalStore(noChanges, audioSupported, () => false);
  const [on, setOn] = useStoredState(SOUND_KEY, true, "local");
  if (!supported) return null;
  return (
    <section aria-label="Sound" className="card mb-4 max-w-xl space-y-3 p-4 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-semibold">{on ? "Sound is on in this browser" : "Sound is off in this browser"}</p>
          <p className="text-xs text-muted-foreground">
            {on
              ? "A short chime plays when a new notification arrives while MegooColab is open."
              : "Turn it on to hear a short chime when a new notification arrives while MegooColab is open."}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" onClick={playChime}>Play sound</Button>
          <Button variant={on ? "ghost" : "primary"} onClick={() => setOn(!on)}>
            {on ? "Turn off" : "Turn on"}
          </Button>
        </div>
      </div>
      <p className="border-t border-line pt-3 text-xs text-muted-foreground">
        Browsers allow sound only after you have clicked or typed in a tab, so a tab you just reloaded stays silent until then.
      </p>
    </section>
  );
}
```

### D. `frontend/src/components/notifications/__tests__/SoundSetting.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SoundSetting } from "@/components/notifications/SoundSetting";
import { playChime } from "@/lib/beep";

vi.mock("@/lib/beep", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/beep")>()), playChime: vi.fn() }));

beforeEach(() => {
  vi.stubGlobal("AudioContext", class {});
  vi.mocked(playChime).mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});
```

The tests:

- "is on by default": the text "Sound is on in this browser", the line "A short chime plays when a new notification arrives while MegooColab is open.", the buttons "Play sound" and "Turn off", and the small print.
- "Turn off stores false and changes the text and the button": click "Turn off". Then `localStorage.getItem("notifications.sound")` is `"false"`, the text reads "Sound is off in this browser" with the "Turn it on to hear…" line, and a "Turn on" button shows.
- "Turn on stores true": set `localStorage` to `"false"` before rendering. It shows off. Click "Turn on": stored `"true"`, and the text reads on.
- "Play sound plays": click "Play sound": `playChime` called once.
- "is not shown without Web Audio": `vi.unstubAllGlobals()` before rendering: `container` is empty.

### E. Browser test, part 6 of `notifications.spec.ts`

Add this at the end of the test `"notifications reach the right people"`, after part 5. Use a mention, not an assignment: in part 4 Bea turned in-app assignments off.

```ts
  // 6. with MegooColab open, a new notification chimes once Bea has clicked in the tab; with the sound off it only
  // raises the bell. The page's AudioContext is swapped for a recorder of the notes played.
  await bea.ctx.addInitScript(() => {
    const w = window as unknown as { __notes: number[]; AudioContext: unknown };
    w.__notes = [];
    w.AudioContext = class {
      state = "suspended";
      currentTime = 0;
      destination = {};
      async resume() {
        this.state = "running";
      }
      createGain() {
        return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} };
      }
      createOscillator() {
        const osc = { type: "sine", frequency: { value: 0 }, connect() {}, start: () => w.__notes.push(osc.frequency.value), stop() {} };
        return osc;
      }
    };
  });
  const notes = () => beaPage.evaluate(() => (window as unknown as { __notes: number[] }).__notes);
  const unread = async () => (await get<{ count: number }>(bea.ctx.request, "/api/notifications/unread-count")).count;
  const mentionBea = (text: string) => post(request, "/api/tasks/NOT-1/comments", { body_md: `${text} @[${BEA.name}](user:${bea.id})` });
  await beaPage.goto("/projects");
  await beaPage.locator("main").click({ position: { x: 5, y: 5 } }); // browsers play sound only after a click or a key
  let count = await unread();
  await mentionBea("One more look,");
  await expect(bell(beaPage)).toHaveText(String(count + 1), { timeout: 15_000 });
  await expect.poll(notes).toEqual([784, 1175]);

  await beaPage.goto("/settings/notifications");
  const sound = beaPage.getByRole("region", { name: "Sound" });
  await expect(sound.getByText("Sound is on in this browser")).toBeVisible();
  await sound.getByRole("button", { name: "Turn off" }).click(); // also the click that lets this tab play sound
  await expect(sound.getByText("Sound is off in this browser")).toBeVisible();
  expect(await beaPage.evaluate(() => localStorage.getItem("notifications.sound"))).toBe("false");
  count = await unread();
  await mentionBea("And the title,");
  await expect(bell(beaPage)).toHaveText(String(count + 1), { timeout: 15_000 });
  expect(await notes()).toEqual([]);
```

The tab chimes inside the same `onmessage` call that starts the bell's refetch. So once the bell shows the new count, any chime has already been recorded, and the final `[]` check is reliable. The reload of `/settings/notifications` starts a fresh page, with a fresh gap and no lock held, so only the switch keeps that page silent.

## Steps

1. Add `lib/beep.ts`: the switch, the unlock and the guarded two-tone chime.
2. Chime on `notification.created` and unlock audio on the tab's first click or key.
3. Add the Sound card to Settings → Notifications.
4. Browser test and docs for the notification chime.

## Final verification

```bash
cd frontend
npx tsc --noEmit
npx eslint src/lib/beep.ts src/lib/realtime.ts "src/app/(app)/layout.tsx" "src/app/(app)/settings/notifications/page.tsx" src/components/notifications/SoundSetting.tsx src/lib/__tests__/beep.test.ts src/lib/__tests__/realtime.test.ts src/components/notifications/__tests__/SoundSetting.test.tsx e2e/notifications.spec.ts
npm test
```

Then run the browser test on a fresh `megoo-e2e` stack, following AGENTS.md: stop `megoocolab-dev-caddy-1`, run `$C down -v; $C up -d --build --wait`, then `cd frontend && npx playwright test e2e/notifications.spec.ts --reporter=line`, then `$C down -v` and `docker start megoocolab-dev-caddy-1`. CI does not run browser tests, so this run is manual.

Last, a manual check by ear in a real browser: Play sound sounds like the approved two-tone chime. With two tabs open and both clicked, one notification gives one chime.
