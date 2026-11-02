import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsTab } from "@/components/hub/ToolsTab";
import { machineState, type HubMachine } from "@/lib/hub";

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

const tool = (name: string, s: string | null) => ({ tool_id: name, name, kind: "mcp", ticked: true, programs: [{ program: "claude_code", state: s, detail: "" }] });
const machine = (over: Record<string, unknown>) =>
  ({
    token_id: "t1", name: "Laptop", os: "macos", online: false, supports_tools: true, pending: false, reported_at: null,
    out_of_step: false, agents: [], tools: [], runner_version: null, ...over,
  }) as unknown as HubMachine;

const MACHINES = [
  machine({}),
  machine({
    token_id: "t2", name: "Workstation", os: "windows", online: true, out_of_step: true,
    tools: [tool("ctx", "installed"), tool("ui", "update_ready"), tool("db", "will_remove")],
  }),
  machine({ token_id: "t3", name: "Server", os: "linux", online: true, tools: [tool("ctx", "installed")] }),
];

beforeEach(() => {
  search = "tab=tools";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/hub/machines") return new Response(JSON.stringify(MACHINES));
    if (url === "/api/hub/prefs") return new Response(JSON.stringify({ auto_default: false }));
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
      <ToolsTab />
    </QueryClientProvider>,
  );
}

describe("ToolsTab", () => {
  it("lists machines with their state", async () => {
    show();
    const list = await screen.findByRole("navigation", { name: "Machines" });
    expect(within(list).getByRole("button", { name: /Laptop/ })).toHaveTextContent("macOS · not connected");
    expect(within(list).getByRole("button", { name: /Workstation/ })).toHaveTextContent("Windows · 2 changes to push");
    expect(within(list).getByRole("button", { name: /Server/ })).toHaveTextContent("Linux · up to date");
  });

  it("shows the chosen machine's tools", async () => {
    search = "tab=tools&machine=t2";
    show();
    expect(await screen.findByRole("region", { name: 'Tools on "Workstation"' })).toBeInTheDocument();
  });

  it("machine=new shows the first machine", async () => {
    search = "tab=tools&machine=new";
    show();
    expect(await screen.findByRole("region", { name: 'Tools on "Laptop"' })).toBeInTheDocument();
  });

  it("keeps the default-set switch", async () => {
    show();
    expect(await screen.findByRole("checkbox", { name: "When I add an agent on a new machine, install my default set there" })).toBeInTheDocument();
  });

  it("points to the Runner tab when there are no machines", async () => {
    MACHINES.splice(0, MACHINES.length);
    show();
    expect(await screen.findByText("No machines yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runner" })).toHaveAttribute("href", "/settings/agents?tab=runner");
  });
});

describe("machineState", () => {
  it("says what a push would do, or why there is nothing to push", () => {
    expect(machineState(machine({ online: true, out_of_step: true, tools: [tool("a", "will_install")] }))).toBe("1 change to push");
    expect(machineState(machine({ online: true, out_of_step: true, pending: true }))).toBe("changes to push");
    expect(machineState(machine({ online: true, out_of_step: true, tools: [tool("a", "conflict")] }))).toBe("needs a look");
    expect(machineState(machine({ online: true }))).toBe("up to date");
    expect(machineState(machine({ online: false, out_of_step: true }))).toBe("not connected");
  });
});
