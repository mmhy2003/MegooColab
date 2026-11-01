import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SharedToolView } from "@/components/hub/SharedToolView";
import type { HubTool } from "@/lib/hub";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const base = {
  id: "t1", version: 2, rev: 3, owner: { id: "u2", name: "Mona" }, is_copy: false, source_state: null, removed: false,
  secrets_missing: false, read_only_safe: false, sharing: null, secrets: [], source: null, flagged: [], can_edit: false,
  description: "",
};
const SKILL = {
  ...base, kind: "skill", name: "ui-review", runs_code: true, spec: null,
  files: [{ path: "SKILL.md", size: 10, runs_on: null }, { path: "scripts/contrast.sh", size: 4, runs_on: ["linux", "macos"] }],
} as unknown as HubTool;
const STDIO = {
  ...base, kind: "mcp", name: "ctx", runs_code: false, files: null,
  spec: { transport: "stdio", url: null, headers: [], command: { command: "npx", args: ["-y", "pkg"] }, os_commands: {},
    env: [{ name: "API_KEY", value: "", secret: true }], acknowledged: [] },
  secrets: [{ name: "API_KEY", set: false }],
} as unknown as HubTool;

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
beforeEach(() => {
  push.mockClear();
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/hub/tools/t1/copy") return new Response(JSON.stringify({ ...SKILL, id: "c1" }), { status: 201 });
    if (url.startsWith("/api/hub/tools/t1/file")) return new Response(JSON.stringify({ path: "scripts/contrast.sh", size: 4, text: "echo" }));
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const wrap = (tool: HubTool) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SharedToolView tool={tool} />
    </QueryClientProvider>,
  );

describe("SharedToolView", () => {
  it("a skill with a script warns and lists the script", async () => {
    wrap(SKILL);
    expect(screen.getByText("by Mona")).toBeInTheDocument();
    const warning = screen.getByRole("note");
    expect(warning).toHaveTextContent("This skill includes files your agents may run on your machine:");
    expect(warning).toHaveTextContent("scripts/contrast.sh");
    fireEvent.click(screen.getByRole("button", { name: "scripts/contrast.sh" }));
    expect(await screen.findByText("echo")).toBeInTheDocument();
  });

  it("Add to my library copies it and opens the copy", async () => {
    wrap(SKILL);
    fireEvent.click(screen.getByRole("button", { name: "Add to my library" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/hub/c1"));
    expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/hub/tools/t1/copy" && i?.method === "POST")).toBe(true);
  });

  it("a command MCP shows what it runs and what it needs", () => {
    wrap(STDIO);
    expect(screen.getByText("needs API_KEY")).toBeInTheDocument();
    expect(screen.getByText(/npx -y pkg/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("This MCP runs a program on your machine: npx");
  });
});
