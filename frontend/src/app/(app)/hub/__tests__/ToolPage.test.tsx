import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ToolPage from "@/app/(app)/hub/[id]/page";
import NewMcpPage from "@/app/(app)/hub/new-mcp/page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useParams: () => ({ id: "t1" }),
  usePathname: () => "/hub/t1",
  useSearchParams: () => new URLSearchParams(),
}));

const SPEC = {
  transport: "http", url: "https://mcp.example.com/mcp", command: null, os_commands: {}, env: [], acknowledged: [],
  headers: [{ name: "Authorization", value: "", secret: true }, { name: "X-Org", value: "", secret: true }],
};
const TOOL = {
  id: "t1", kind: "mcp", name: "ctx", description: "Reads docs", version: 1, rev: 1, owner: { id: "u1", name: "Ada" },
  is_copy: false, source_state: null, removed: false, secrets_missing: true, runs_code: false, read_only_safe: false,
  sharing: { teams: [], users: [], everyone: false }, spec: SPEC, files: null, source: null, flagged: [], can_edit: true,
  secrets: [{ name: "Authorization", set: false }, { name: "X-Org", set: true }],
};

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;

beforeEach(() => {
  push.mockClear();
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "Ada", email: "a@x.io", role: "member" } }));
    if (url === "/api/hub/tools" && init?.method === "POST") return new Response(JSON.stringify({ ...TOOL, id: "t9" }), { status: 201 });
    if (url.startsWith("/api/hub/tools/t1")) return new Response(JSON.stringify(TOOL));
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

describe("a tool of mine", () => {
  it("shows Setup, Secrets and Sharing", async () => {
    wrap(<ToolPage />);
    expect(await screen.findByRole("heading", { name: "Setup" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Secrets" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sharing" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("ctx");
  });

  it("saves only the secrets typed in", async () => {
    wrap(<ToolPage />);
    const secrets = within((await screen.findByRole("heading", { name: "Secrets" })).closest("section")!);
    expect(secrets.getByText("not set")).toBeInTheDocument();
    expect(secrets.getByText("set")).toBeInTheDocument();
    fireEvent.change(secrets.getByLabelText("Authorization"), { target: { value: "Bearer abc" } });
    fireEvent.click(secrets.getByRole("button", { name: "Save secrets" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => u === "/api/hub/tools/t1/secrets" && i?.method === "PUT");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ values: { Authorization: "Bearer abc" } });
    });
  });

  it("new MCP posts and opens the tool", async () => {
    wrap(<NewMcpPage />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "ctx" } });
    fireEvent.change(screen.getByLabelText("Address"), { target: { value: "https://mcp.example.com/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: "Add MCP" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/hub/t9"));
  });
});

describe("a copy of someone's tool", () => {
  const COPY = {
    ...TOOL, is_copy: true, can_edit: false, source_state: "update_available", version: 1,
    source: { id: "s1", name: "ctx", owner_name: "Mona", version: 2 },
  };

  it("offers the update and making it my own, keeps the setup read-only", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/hub/tools/t1") return new Response(JSON.stringify(COPY));
      return new Response(JSON.stringify(COPY));
    });
    wrap(<ToolPage />);
    expect(await screen.findByText("Copy of ctx by Mona · v1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sharing" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Take update" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/hub/tools/t1/update" && i?.method === "POST")).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: "Make it my own" }));
    expect(await screen.findByText("It stops getting updates from Mona.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Safe in read-only runs" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => u === "/api/hub/tools/t1" && i?.method === "PATCH");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ read_only_safe: true });
    });
  });

  it("a removed tool only says so", async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ ...COPY, removed: true })));
    wrap(<ToolPage />);
    expect(await screen.findByText(/removed by an admin/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take update" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("someone else's tool shows the shared view", async () => {
    fetchMock.mockImplementation(async () =>
      new Response(JSON.stringify({ ...TOOL, sharing: null, can_edit: false, owner: { id: "u2", name: "Mona" } })),
    );
    wrap(<ToolPage />);
    expect(await screen.findByRole("button", { name: "Add to my library" })).toBeInTheDocument();
    expect(screen.getByText("needs Authorization")).toBeInTheDocument();
  });
});
