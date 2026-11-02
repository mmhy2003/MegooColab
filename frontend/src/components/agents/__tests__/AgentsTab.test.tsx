import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentsTab } from "@/components/agents/AgentsTab";
import type { AccessToken, Agent, Project } from "@/lib/types";

let search = "";
const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

const OWNER = { id: "u1", name: "Mo", email: "mo@x.io" };
const agent = (over: Partial<Agent>): Agent =>
  ({
    id: "a1", name: "Mo's Claude Code", program: "claude_code", answer_mode: "manual", max_concurrent_runs: 1,
    running: 0, status: "online", problems: [], bindings: [], owner: OWNER, model: null, effort: null,
    known_models: [], machine: null, runner: null, ...over,
  }) as Agent;

const AGENTS = [
  agent({
    machine: { token_id: "t1", name: "Workstation", expired: false },
    bindings: [
      { project_id: "p1", project_key: "PAY", local_path: "C:\\code\\payments" },
      { project_id: "p2", project_key: "WEB", local_path: "C:\\code\\web" },
    ],
  }),
  agent({ id: "a2", name: "Mo's Codex", program: "codex" }),
];
const PROJECTS = [
  { id: "p1", key: "PAY", name: "Payments" },
  { id: "p2", key: "WEB", name: "Website" },
] as unknown as Project[];

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
const onChanged = vi.fn(async () => undefined);

beforeEach(() => {
  search = "";
  push.mockClear();
  replace.mockClear();
  onChanged.mockClear();
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return new Response(JSON.stringify(AGENTS[0]));
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return new Response("[]");
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(agents: Agent[] = AGENTS, hasMachines = true) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AgentsTab agents={agents} projects={PROJECTS} tokens={[] as AccessToken[]} hasMachines={hasMachines} onChanged={onChanged} />
    </QueryClientProvider>,
  );
}

const sent = (method: string) => {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === method);
  return call && { url: call[0], body: call[1]?.body ? JSON.parse(String(call[1].body)) : undefined };
};

describe("AgentsTab", () => {
  it("lists each agent with its machine and project count", () => {
    show();
    const list = screen.getByRole("navigation", { name: "Agents" });
    expect(within(list).getByRole("button", { name: /Mo's Claude Code/ })).toHaveTextContent("Workstation · 2 projects");
    expect(within(list).getByRole("button", { name: /Mo's Codex/ })).toHaveTextContent("Not linked · 0 projects");
  });

  it("shows the first agent when none is chosen, and the chosen one from the address", () => {
    show();
    expect(screen.getByRole("region", { name: "Mo's Claude Code" })).toBeInTheDocument();
    cleanup();
    search = "agent=a2";
    show();
    expect(screen.getByRole("region", { name: "Mo's Codex" })).toBeInTheDocument();
  });

  it("clicking a row chooses it", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: /Mo's Codex/ }));
    expect(push).toHaveBeenCalledWith("/settings/agents?agent=a2", { scroll: false });
  });

  it("renames from the menu", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Actions for Mo's Claude Code" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename agent" });
    await userEvent.clear(within(dialog).getByLabelText("Name"));
    await userEvent.type(within(dialog).getByLabelText("Name"), "Mo");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent("PATCH")).toEqual({ url: "/api/agents/a1", body: { name: "Mo" } }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("changes the answer mode from the menu", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Actions for Mo's Claude Code" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Answer mode" }));
    const dialog = screen.getByRole("dialog", { name: "Answer mode" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Answer mode"), "auto");
    expect(dialog).toHaveTextContent("Auto: the agent's answers are sent to other agents without your approval");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent("PATCH")).toEqual({ url: "/api/agents/a1", body: { answer_mode: "auto" } }));
  });

  it("deleting the chosen agent shows the next one", async () => {
    search = "agent=a1";
    show();
    await userEvent.click(screen.getByRole("button", { name: "Actions for Mo's Claude Code" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(sent("DELETE")?.url).toBe("/api/agents/a1"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/settings/agents", { scroll: false }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("points to the Runner tab when there are no machines", () => {
    show([], false);
    expect(screen.getByText("No agents yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runner" })).toHaveAttribute("href", "/settings/agents?tab=runner");
  });
});
