import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { RunnerSetup } from "@/components/agents/RunnerSetup";

afterEach(cleanup);

const value = (label: string) => (screen.getByLabelText(label) as HTMLTextAreaElement).value;

describe("RunnerSetup", () => {
  it("opens on Set up while there are no agents, with this server's address in the sign-in command", () => {
    render(<RunnerSetup hasAgents={false} />);
    expect(screen.getByRole("tab", { name: "Set up" })).toHaveAttribute("aria-selected", "true");
    expect(value("2. Sign in")).toBe(`megoocolab-runner login --url ${window.location.origin} --token <paste a runner token>`);
    expect(value("3. Check it's ready")).toBe("megoocolab-runner doctor");
    expect(value("4. Start it in this terminal")).toBe("megoocolab-runner run");
  });

  it("opens on Keep it running once there are agents, and installs and starts the service in one line", async () => {
    render(<RunnerSetup hasAgents />);
    expect(screen.getByRole("tab", { name: "Keep it running" })).toHaveAttribute("aria-selected", "true");
    const turnOn = "Turn it on: register it and start it now";

    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value(turnOn)).toBe("megoocolab-runner service install; megoocolab-runner service start");
    expect(screen.queryByLabelText("Linux: keep it running after you sign out")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value(turnOn)).toBe("megoocolab-runner service install && megoocolab-runner service start");
    expect(value("Linux: keep it running after you sign out")).toBe("loginctl enable-linger $USER");
    expect(value("Is it running?")).toBe("megoocolab-runner service status");
    expect(value("Stop it for now (it starts again at your next sign-in)")).toBe("megoocolab-runner service stop");
    expect(value("Start it again")).toBe("megoocolab-runner service start");
    expect(value("Turn it off (stop it and remove it from sign-in)")).toBe("megoocolab-runner service uninstall");
  });

  it("updates in three steps with the platform's update command", async () => {
    render(<RunnerSetup hasAgents />);
    await userEvent.click(screen.getByRole("tab", { name: "Update" }));
    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value("1. Stop it, if it runs in the background")).toBe("megoocolab-runner service stop");
    expect(value("2. Update")).toBe("scoop update megoocolab-runner");
    expect(value("3. Start the new version")).toBe("megoocolab-runner service start");
    expect(value("Check which version you have")).toBe("megoocolab-runner version");
    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value("2. Update")).toContain("install.sh | sh");
  });

  it("shows where the background log is on each platform", async () => {
    render(<RunnerSetup hasAgents />);
    await userEvent.click(screen.getByRole("tab", { name: "Troubleshoot" }));
    expect(value("Check settings, server access and agents")).toBe("megoocolab-runner doctor");
    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value("Follow the background log")).toBe("Get-Content -Tail 50 -Wait $env:LOCALAPPDATA\\megoocolab\\logs\\runner.log");
    expect(value("Sign in again, then start it")).toBe(
      `megoocolab-runner login --url ${window.location.origin} --token <paste a runner token>; megoocolab-runner service start`,
    );
    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value("Follow the background log (Linux)")).toBe("tail -f ~/.cache/megoocolab/logs/runner.log");
    expect(value("Follow the background log (macOS)")).toBe("tail -f ~/Library/Caches/megoocolab/logs/runner.log");
  });

  it("keeps the tab you chose when the agents arrive", async () => {
    const { rerender } = render(<RunnerSetup />);
    expect(screen.getByRole("tab", { name: "Set up" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Update" }));
    rerender(<RunnerSetup hasAgents />);
    expect(screen.getByRole("tab", { name: "Update" })).toHaveAttribute("aria-selected", "true");
  });
});
