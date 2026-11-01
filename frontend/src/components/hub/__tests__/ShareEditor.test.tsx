import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShareEditor } from "@/components/hub/ShareEditor";
import type { HubTool } from "@/lib/hub";

const SPEC = {
  transport: "stdio", url: null, headers: [], command: { command: "npx", args: ["pkg", "sk-live1234567890"] },
  os_commands: {}, env: [], acknowledged: [],
};
const TOOL = {
  id: "t1", kind: "mcp", name: "ctx", description: "", version: 1, rev: 1, owner: { id: "u1", name: "Ada" },
  is_copy: false, source_state: null, removed: false, secrets_missing: false, runs_code: false, read_only_safe: false,
  sharing: { teams: [], users: [], everyone: false }, spec: SPEC, secrets: [], files: null, source: null,
  flagged: [] as string[], can_edit: true,
} as unknown as HubTool;

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
let sharingStatus = 200;

beforeEach(() => {
  sharingStatus = 200;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "Ada", email: "a@x.io", role: "member" } }));
    if (url === "/api/teams") {
      return new Response(JSON.stringify([
        { id: "tm1", name: "Platform", description: "", member_count: 2, project_count: 0, is_member: true },
        { id: "tm2", name: "Other", description: "", member_count: 2, project_count: 0, is_member: false },
      ]));
    }
    if (url.startsWith("/api/users")) {
      return new Response(JSON.stringify([
        { id: "u1", name: "Ada", email: "a@x.io", role: "member" },
        { id: "u2", name: "Mona", email: "m@x.io", role: "member" },
      ]));
    }
    if (url === "/api/hub/tools/t1/sharing" && init?.method === "PUT") {
      if (sharingStatus !== 200) return new Response(JSON.stringify({ detail: "hub_everyone_off" }), { status: sharingStatus });
      return new Response(JSON.stringify(TOOL));
    }
    if (url === "/api/hub/tools/t1" && init?.method === "PATCH") return new Response(JSON.stringify({ ...TOOL, flagged: [] }));
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderIt = (tool: HubTool) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ShareEditor tool={tool} />
    </QueryClientProvider>,
  );

const body = (url: string, method: string) => {
  const call = fetchMock.mock.calls.find(([u, i]) => u === url && i?.method === method);
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
};

describe("ShareEditor", () => {
  it("offers only my teams, finds people, and saves the choice", async () => {
    renderIt(TOOL);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Platform" }));
    expect(screen.queryByRole("checkbox", { name: "Other" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Find people"), { target: { value: "mo" } });
    fireEvent.click(await screen.findByRole("button", { name: "Add Mona" }));
    expect(screen.queryByRole("button", { name: "Add Ada" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Everyone on MegooColab" }));
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    await waitFor(() => expect(body("/api/hub/tools/t1/sharing", "PUT")).toEqual({ teams: ["tm1"], users: ["u2"], everyone: true }));
  });

  it("holds back sharing while values look like keys, until each is cleared", async () => {
    renderIt({ ...TOOL, flagged: ["args[1]"] });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Platform" }));
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Not a secret: args[1]" }));
    await waitFor(() => expect(body("/api/hub/tools/t1", "PATCH")).toEqual({ spec: { ...SPEC, acknowledged: ["args[1]"] } }));
  });

  it("shows why sharing was refused", async () => {
    sharingStatus = 409;
    renderIt(TOOL);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Everyone on MegooColab" }));
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sharing with everyone is turned off on this MegooColab.");
  });

  it("says Only me when nothing is chosen", async () => {
    renderIt(TOOL);
    expect(await screen.findByText("Only me: nobody else sees it.")).toBeInTheDocument();
  });
});
