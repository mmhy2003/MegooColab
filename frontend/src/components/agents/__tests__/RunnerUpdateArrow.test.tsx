import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunnerUpdateArrow } from "@/components/agents/RunnerUpdateArrow";
import type { RunnerInfo } from "@/lib/types";

const LATEST = { app: null, runner: { latest: "0.2.0", url: "https://github.com/x/releases/tag/runner-v0.2.0" } };

const ME = { user: { id: "u1", name: "Vera", email: "v@x.io", role: "member" } };

function renderArrow(runner: RunnerInfo | null, mine: boolean, updates: object = LATEST) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.includes("/api/auth/me") ? ME : updates), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunnerUpdateArrow runner={runner} ownerId={mine ? "u1" : "u2"} />
    </QueryClientProvider>,
  );
}

async function settle() {
  await new Promise((r) => setTimeout(r, 20));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RunnerUpdateArrow", () => {
  it("tells the owner on Windows how to update", async () => {
    renderArrow({ version: "0.1.0", os: "windows" }, true);
    await userEvent.click(await screen.findByRole("button", { name: "Runner update available" }));
    expect(screen.getAllByText("Runner update: you have 0.1.0, 0.2.0 is out.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("scoop update megoocolab-runner").length).toBeGreaterThan(0);
  });

  it("gives the install command again on macOS and Linux", async () => {
    renderArrow({ version: "0.1.0", os: "linux" }, true);
    await userEvent.click(await screen.findByRole("button", { name: "Runner update available" }));
    expect(screen.getAllByText("curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh").length)
      .toBeGreaterThan(0);
  });

  it("on someone else's agent says the owner can update it", async () => {
    renderArrow({ version: "0.1.0", os: "windows" }, false);
    await userEvent.click(await screen.findByRole("button", { name: "Runner update available" }));
    expect(screen.getAllByText("Runner update: this agent's runner is 0.1.0, 0.2.0 is out. Its owner can update it.").length)
      .toBeGreaterThan(0);
    expect(screen.queryByText("scoop update megoocolab-runner")).toBeNull();
  });

  it.each([
    ["offline", null, LATEST],
    ["a local build", { version: "0.1.0-dev+abc", os: "linux" }, LATEST],
    ["up to date", { version: "0.2.0", os: "linux" }, LATEST],
    ["no release known", { version: "0.1.0", os: "linux" }, { app: null, runner: null }],
  ])("shows nothing when %s", async (_why, runner, updates) => {
    renderArrow(runner, true, updates);
    await settle();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
