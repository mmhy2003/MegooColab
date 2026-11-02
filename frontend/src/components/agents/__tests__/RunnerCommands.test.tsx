import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { RunnerCommands } from "@/components/agents/RunnerCommands";

afterEach(cleanup);

const value = (label: string) => (screen.getByLabelText(label) as HTMLTextAreaElement).value;

describe("RunnerCommands", () => {
  it("installs and starts the service in one line", () => {
    render(<RunnerCommands os="windows" />);
    const turnOn = "Turn it on: register it and start it now";
    expect(value(turnOn)).toBe("megoocolab-runner service install; megoocolab-runner service start");
    expect(screen.queryByLabelText("Linux: keep it running after you sign out")).toBeNull();
    cleanup();
    render(<RunnerCommands os="linux" />);
    expect(value(turnOn)).toBe("megoocolab-runner service install && megoocolab-runner service start");
    expect(value("Linux: keep it running after you sign out")).toBe("loginctl enable-linger $USER");
    expect(value("Is it running?")).toBe("megoocolab-runner service status");
    expect(value("Stop it for now (it starts again at your next sign-in)")).toBe("megoocolab-runner service stop");
    expect(value("Start it again")).toBe("megoocolab-runner service start");
    expect(value("Turn it off (stop it and remove it from sign-in)")).toBe("megoocolab-runner service uninstall");
  });

  it("updates in three steps with the platform's update command", () => {
    render(<RunnerCommands os="windows" />);
    expect(value("1. Stop it, if it runs in the background")).toBe("megoocolab-runner service stop");
    expect(value("2. Update")).toBe("scoop update megoocolab-runner");
    expect(value("3. Start the new version")).toBe("megoocolab-runner service start");
    expect(value("Check which version you have")).toBe("megoocolab-runner version");
    cleanup();
    render(<RunnerCommands os="macos" />);
    expect(value("2. Update")).toContain("install.sh | sh");
  });

  it("shows the background log for the machine's OS", () => {
    render(<RunnerCommands os="macos" />);
    expect(value("Follow the background log")).toBe("tail -f ~/Library/Caches/megoocolab/logs/runner.log");
    cleanup();
    render(<RunnerCommands os="linux" />);
    expect(value("Follow the background log")).toBe("tail -f ~/.cache/megoocolab/logs/runner.log");
    cleanup();
    render(<RunnerCommands os="windows" />);
    expect(value("Follow the background log")).toBe("Get-Content -Tail 50 -Wait $env:LOCALAPPDATA\\megoocolab\\logs\\runner.log");
    expect(value("Check settings, server access and agents")).toBe("megoocolab-runner doctor");
    expect(value("Sign in again, then start it")).toBe(
      `megoocolab-runner login --url ${window.location.origin} --token <paste a runner token>; megoocolab-runner service start`,
    );
  });

  it("asks for the platform when the OS is unknown", async () => {
    render(<RunnerCommands os={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value("Follow the background log (Linux)")).toBe("tail -f ~/.cache/megoocolab/logs/runner.log");
    expect(value("Follow the background log (macOS)")).toBe("tail -f ~/Library/Caches/megoocolab/logs/runner.log");
    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value("2. Update")).toBe("scoop update megoocolab-runner");
  });

  it("has no platform toggle when the OS is known", () => {
    render(<RunnerCommands os="windows" />);
    expect(screen.queryByRole("group", { name: "Platform" })).toBeNull();
  });
});
