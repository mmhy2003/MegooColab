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
  const request = vi.fn((_name: string, _opts: object, cb: (lock: object | null) => unknown) =>
    Promise.resolve(cb(held ? null : { name: "megoo-chime" })),
  );
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

describe("chimeForNotification", () => {
  it("plays two notes, 784 Hz then 1175 Hz, when on and unlocked", async () => {
    const beep = await fresh();
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toEqual([784, 1175]);
  });

  it("stays silent when the sound is off", async () => {
    const beep = await fresh();
    localStorage.setItem("notifications.sound", "false");
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toEqual([]);
  });

  it("stays silent in a tab never clicked, and does not play late once unlocked", async () => {
    const beep = await fresh();
    beep.chimeForNotification();
    expect(played()).toEqual([]);
    beep.unlockAudio();
    expect(played()).toEqual([]);
  });

  it("chimes once for a burst, and again after 2 s", async () => {
    const beep = await fresh();
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toHaveLength(2);
    vi.advanceTimersByTime(1999);
    beep.chimeForNotification();
    expect(played()).toHaveLength(2);
    vi.advanceTimersByTime(1);
    beep.chimeForNotification();
    expect(played()).toHaveLength(4);
  });

  it("stays silent when another tab holds the lock", async () => {
    const beep = await fresh();
    const request = stubLocks(true);
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toEqual([]);
    expect(request).toHaveBeenCalledWith("megoo-chime", { ifAvailable: true }, expect.any(Function));
  });

  it("plays when it wins the lock", async () => {
    const beep = await fresh();
    stubLocks(false);
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toEqual([784, 1175]);
  });

  it("plays without Web Locks", async () => {
    const beep = await fresh();
    beep.unlockAudio();
    beep.chimeForNotification();
    expect(played()).toEqual([784, 1175]);
  });
});

describe("playChime", () => {
  it("plays even when the sound is off, without an earlier click", async () => {
    const beep = await fresh();
    localStorage.setItem("notifications.sound", "false");
    beep.playChime();
    expect(played()).toEqual([784, 1175]);
  });
});

describe("isSoundOn", () => {
  it("is on with nothing stored", async () => {
    const beep = await fresh();
    expect(beep.isSoundOn()).toBe(true);
  });

  it("is on with true stored", async () => {
    const beep = await fresh();
    localStorage.setItem("notifications.sound", "true");
    expect(beep.isSoundOn()).toBe(true);
  });

  it("is off with false stored", async () => {
    const beep = await fresh();
    localStorage.setItem("notifications.sound", "false");
    expect(beep.isSoundOn()).toBe(false);
  });
});

describe("audioSupported", () => {
  it("is true with Web Audio", async () => {
    const beep = await fresh();
    expect(beep.audioSupported()).toBe(true);
  });

  it("is false without Web Audio", async () => {
    const beep = await fresh();
    vi.unstubAllGlobals();
    expect(beep.audioSupported()).toBe(false);
  });
});

describe("listenForUnlock", () => {
  it("unlocks on the first pointerdown, then stops listening", async () => {
    const beep = await fresh();
    const stop = beep.listenForUnlock();
    window.dispatchEvent(new Event("pointerdown"));
    await Promise.resolve();
    expect(FakeContext.instances).toHaveLength(1);
    expect(FakeContext.instances[0].state).toBe("running");
    window.dispatchEvent(new Event("pointerdown"));
    window.dispatchEvent(new Event("keydown"));
    expect(FakeContext.instances[0].resume).toHaveBeenCalledTimes(1);
    stop();
  });

  it("unlocks on a key", async () => {
    const beep = await fresh();
    const stop = beep.listenForUnlock();
    window.dispatchEvent(new Event("keydown"));
    await Promise.resolve();
    expect(FakeContext.instances[0].state).toBe("running");
    stop();
  });

  it("the cleanup removes the listeners", async () => {
    const beep = await fresh();
    const stop = beep.listenForUnlock();
    stop();
    window.dispatchEvent(new Event("pointerdown"));
    expect(FakeContext.instances).toHaveLength(0);
  });
});
