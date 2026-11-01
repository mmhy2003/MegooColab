import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MachineTools } from "@/components/hub/MachineTools";
import type { HubMachine } from "@/lib/hub";
import { answer } from "@/test/answer";

const state = (program: string, s: string | null, detail = "") => ({ program, state: s, detail });
const row = (id: string | null, name: string, ticked: boolean, ...programs: ReturnType<typeof state>[]) => ({
  tool_id: id, name, kind: "mcp", ticked, programs,
});

const MACHINE = {
  token_id: "m1", name: "hammad-desktop", os: "windows", online: true, supports_tools: true, pending: false,
  reported_at: null, out_of_step: true,
  agents: [{ id: "a1", name: "Builder", program: "claude_code" }, { id: "a2", name: "Reviewer", program: "codex" }],
  tools: [
    row("t1", "ctx", true, state("claude_code", "installed"), state("codex", "update_ready")),
    row("t2", "pw", false, state("claude_code", null), state("codex", null)),
    row("t3", "mine", true, state("claude_code", "conflict"), state("codex", "will_install")),
    row("t4", "gone", false, state("claude_code", "removed")),
    row(null, "old", false, state("claude_code", "will_remove")),
    row("t5", "nokey", true, state("claude_code", "key_missing")),
    row("t6", "bad", true, state("claude_code", "failed", "config.toml could not be read")),
    row("t7", "nowin", true, state("claude_code", "not_available"), state("codex", "not_supported")),
    row("t8", "wait", true, state("claude_code", "waiting")),
    row("t9", "edit", true, state("claude_code", "changed")),
  ],
} as unknown as HubMachine;

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(JSON.stringify(MACHINE)));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const wrap = (machine: HubMachine) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MachineTools machine={machine} />
    </QueryClientProvider>,
  );

const pushBody = () => {
  const call = fetchMock.mock.calls.find(([u, i]) => u === "/api/hub/machines/m1/push" && i?.method === "POST");
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
};

describe("MachineTools", () => {
  it("names the machine, its system and its agents, and shows each state in words", () => {
    wrap(MACHINE);
    expect(screen.getByRole("heading", { name: 'Tools on "hammad-desktop"' })).toBeInTheDocument();
    expect(screen.getByText("Windows · connected")).toBeInTheDocument();
    expect(screen.getByText("Agents here: Builder (Claude Code), Reviewer (Codex)")).toBeInTheDocument();
    const words: [string, string][] = [
      ["ctx", "Claude Code: installed"], ["ctx", "Codex: update ready"], ["mine", "Claude Code: made by hand on this machine"],
      ["mine", "Codex: will install"], ["gone", "Claude Code: push to uninstall"], ["old", "Claude Code: will remove"],
      ["nokey", "Claude Code: key missing: can't install yet"], ["bad", "Claude Code: failed: config.toml could not be read"],
      ["nowin", "Claude Code: not available on Windows"], ["nowin", "Codex: not supported by Codex"],
      ["wait", "Claude Code: waiting for the machine to come online"], ["edit", "Claude Code: changed on this machine"],
    ];
    for (const [name, text] of words) {
      expect(within(screen.getByRole("listitem", { name })).getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByRole("checkbox", { name: "gone" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "old" })).toBeDisabled();
  });

  it("ticking and pushing sends the ticked tools", async () => {
    const clean = { ...MACHINE, tools: [MACHINE.tools[0], MACHINE.tools[1]] } as HubMachine;
    wrap(clean);
    fireEvent.click(screen.getByRole("checkbox", { name: "pw" }));
    fireEvent.click(screen.getByRole("button", { name: "Push 2 changes" }));
    await waitFor(() => expect(pushBody()).toEqual({ tool_ids: ["t1", "t2"], take_over: [] }));
  });

  it("Take over adds the tool to take_over", async () => {
    const one = { ...MACHINE, tools: [MACHINE.tools[2]] } as HubMachine;
    wrap(one);
    fireEvent.click(screen.getByRole("button", { name: "Take over mine" }));
    fireEvent.click(screen.getByRole("button", { name: "Push 1 change" }));
    await waitFor(() => expect(pushBody()).toEqual({ tool_ids: ["t3"], take_over: ["t3"] }));
  });

  it("asks before putting the library's version back over a hand edit", async () => {
    const one = { ...MACHINE, tools: [MACHINE.tools[9]] } as HubMachine;
    wrap(one);
    fireEvent.click(screen.getByRole("button", { name: "Push 1 change" }));
    expect(await screen.findByText("This puts your library's version back over the hand edits on this machine.")).toBeInTheDocument();
    await answer("Push");
    await waitFor(() => expect(pushBody()).toEqual({ tool_ids: ["t9"], take_over: [] }));
  });

  it("nothing to push: the button is off", () => {
    const done = { ...MACHINE, out_of_step: false, tools: [row("t1", "ctx", true, state("claude_code", "installed"))] } as HubMachine;
    wrap(done);
    expect(screen.getByRole("button", { name: "Push 0 changes" })).toBeDisabled();
  });

  it("a runner that is too old only says so", () => {
    wrap({ ...MACHINE, supports_tools: false } as HubMachine);
    expect(screen.getByText("Update the runner to use the Tool Hub.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Push/ })).not.toBeInTheDocument();
  });
});
