import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunnerTab } from "@/components/agents/RunnerTab";

let search = "";
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

const machine = (over: Record<string, unknown>) => ({
  token_id: "t1", name: "Workstation", os: "windows", online: true, supports_tools: true, pending: false,
  reported_at: null, out_of_step: false, tools: [], runner_version: "0.5.0",
  agents: [
    { id: "a1", name: "Mo's Claude Code", program: "claude_code" },
    { id: "a2", name: "Mo's Codex", program: "codex" },
    { id: "a3", name: "Mo's OMP", program: "omp" },
  ],
  ...over,
});
let machines: unknown[];

beforeEach(() => {
  search = "tab=runner";
  push.mockClear();
  machines = [
    machine({}),
    machine({ token_id: "t2", name: "Laptop", os: "macos", online: false, runner_version: null, agents: [{ id: "a4", name: "Mo's OMP", program: "omp" }] }),
    machine({ token_id: "t3", name: "New box", os: null, online: false, runner_version: null, agents: [] }),
  ];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/hub/machines") return new Response(JSON.stringify(machines));
    if (url.includes("/api/auth/me")) return new Response(JSON.stringify({ user: { id: "u1", name: "Mo", email: "m@x.io", role: "member" } }));
    if (url.includes("updates")) return new Response(JSON.stringify({ app: null, runner: { latest: "0.6.0", url: "https://x" } }));
    return new Response("[]");
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RunnerTab onAddAgent={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("RunnerTab", () => {
  it("lists machines with version and agent count", async () => {
    show();
    const list = await screen.findByRole("navigation", { name: "Machines" });
    expect(within(list).getByRole("button", { name: /Workstation/ })).toHaveTextContent("Windows · runner 0.5.0 · 3 agents");
    expect(within(list).getByRole("button", { name: /Laptop/ })).toHaveTextContent("macOS · 1 agent");
  });

  it("shows the update arrow for an old runner", async () => {
    show();
    expect(await screen.findByRole("button", { name: "Runner update available" })).toBeInTheDocument();
  });

  it("shows the chosen machine with its agents and commands", async () => {
    search = "tab=runner&machine=t2";
    show();
    const region = await screen.findByRole("region", { name: "Laptop" });
    expect(region).toHaveTextContent("Not connected");
    expect(region).toHaveTextContent("Agents on it: Mo's OMP (OMP)");
    expect(within(region).getByLabelText("Follow the background log")).toHaveValue("tail -f ~/Library/Caches/megoocolab/logs/runner.log");
  });

  it("a machine that never connected says how to start over", async () => {
    search = "tab=runner&machine=t3";
    show();
    const region = await screen.findByRole("region", { name: "New box" });
    expect(region).toHaveTextContent(
      "This machine hasn't connected yet. Its token was shown once when you made it; if you no longer have it, set the machine up again with Add a machine and revoke this one under Access tokens.",
    );
    expect(within(region).getByRole("link", { name: "Access tokens" })).toHaveAttribute("href", "/settings/tokens");
    expect(within(region).queryByText("Keep it running")).toBeNull();
  });

  it("opens Add a machine from the list, and when there are no machines", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "+ Add a machine" }));
    expect(push).toHaveBeenCalledWith("/settings/agents?tab=runner&machine=new", { scroll: false });
    cleanup();
    search = "tab=runner&machine=new";
    show();
    expect(await screen.findByLabelText("Machine name")).toBeInTheDocument();
    cleanup();
    search = "tab=runner";
    machines = [];
    show();
    expect(await screen.findByLabelText("Machine name")).toBeInTheDocument();
  });
});
