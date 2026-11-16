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
