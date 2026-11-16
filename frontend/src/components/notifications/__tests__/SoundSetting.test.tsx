import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SoundSetting } from "@/components/notifications/SoundSetting";
import { playChime } from "@/lib/beep";

vi.mock("@/lib/beep", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/beep")>()), playChime: vi.fn() }));

const ON_LINE = "A short chime plays when a new notification arrives while MegooColab is open.";
const OFF_LINE = "Turn it on to hear a short chime when a new notification arrives while MegooColab is open.";
const SMALL_PRINT = "Browsers allow sound only after you have clicked or typed in a tab, so a tab you just reloaded stays silent until then.";

beforeEach(() => {
  vi.stubGlobal("AudioContext", class {});
  vi.mocked(playChime).mockClear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("SoundSetting", () => {
  it("is on by default", () => {
    render(<SoundSetting />);
    expect(screen.getByText("Sound is on in this browser")).toBeTruthy();
    expect(screen.getByText(ON_LINE)).toBeTruthy();
    expect(screen.getByText(SMALL_PRINT)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play sound" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeTruthy();
  });

  it("Turn off stores false and changes the text and the button", async () => {
    render(<SoundSetting />);
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(localStorage.getItem("notifications.sound")).toBe("false");
    expect(screen.getByText("Sound is off in this browser")).toBeTruthy();
    expect(screen.getByText(OFF_LINE)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn on" })).toBeTruthy();
  });

  it("Turn on stores true", async () => {
    localStorage.setItem("notifications.sound", "false");
    render(<SoundSetting />);
    expect(screen.getByText("Sound is off in this browser")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(localStorage.getItem("notifications.sound")).toBe("true");
    expect(screen.getByText("Sound is on in this browser")).toBeTruthy();
  });

  it("Play sound plays", async () => {
    render(<SoundSetting />);
    await userEvent.click(screen.getByRole("button", { name: "Play sound" }));
    expect(playChime).toHaveBeenCalledTimes(1);
  });

  it("is not shown without Web Audio", () => {
    vi.unstubAllGlobals();
    const { container } = render(<SoundSetting />);
    expect(container.innerHTML).toBe("");
  });
});
