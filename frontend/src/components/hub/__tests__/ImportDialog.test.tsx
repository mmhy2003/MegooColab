import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ImportDialog } from "@/components/hub/ImportDialog";

const ITEMS = [
  {
    index: 0, kind: "mcp", name: "gh", programs: ["claude_code", "codex"], problem: null, exists_in_library: false, files: null,
    mcp: { transport: "stdio", url: null, command: "npx", args: ["-y", "gh-mcp"], headers: [],
      env: [{ name: "GITHUB_TOKEN", value_masked: "••••1234", suggested_secret: true },
            { name: "LOG_LEVEL", value_masked: "info", suggested_secret: false }] },
  },
  { index: 1, kind: "skill", name: "notes", programs: ["codex"], problem: null, exists_in_library: true, mcp: null,
    files: [{ path: "SKILL.md", size: 20, runs_on: null }] },
  { index: 2, kind: "mcp", name: "old", programs: ["claude_code"], problem: "not supported: sse", exists_in_library: false,
    mcp: null, files: null },
];

let polls = 0;
let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
beforeEach(() => {
  polls = 0;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/hub/machines/m1/scan") return new Response(JSON.stringify({ scan_id: "s1" }), { status: 202 });
    if (url === "/api/hub/scans/s1") {
      polls += 1;
      return new Response(JSON.stringify(polls < 2 ? { status: "waiting", items: [] } : { status: "done", items: ITEMS }));
    }
    if (url === "/api/hub/scans/s1/accept" && init?.method === "POST") return new Response(JSON.stringify([]));
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const wrap = (onClose = vi.fn()) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImportDialog tokenId="m1" pollMs={10} onClose={onClose} />
    </QueryClientProvider>,
  );

describe("ImportDialog", () => {
  it("lists what was found, masked, with suggested secrets ticked, and adds the chosen ones", async () => {
    const onClose = vi.fn();
    wrap(onClose);
    expect(await screen.findByText("••••1234")).toBeInTheDocument();
    expect(screen.getByText("Claude Code, Codex")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "GITHUB_TOKEN is secret" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "LOG_LEVEL is secret" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Bring in notes" })).not.toBeChecked();
    expect(screen.getByText("Already in your library")).toBeInTheDocument();
    expect(screen.getByText("not supported: sse")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Bring in old" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name for gh"), { target: { value: "github" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 1 to my library" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => u === "/api/hub/scans/s1/accept");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        items: [{ index: 0, name: "github", secret: ["GITHUB_TOKEN"], description: "" }],
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("says so when the machine does not answer", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === "/api/hub/machines/m1/scan"
        ? new Response(JSON.stringify({ scan_id: "s1" }), { status: 202 })
        : new Response(JSON.stringify({ status: "waiting", items: [] })),
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ImportDialog tokenId="m1" pollMs={5} timeoutMs={50} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("The machine didn't answer. Try again.")).toBeInTheDocument();
  });

  it("shows why the scan could not start", async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: "hub_runner_offline" }), { status: 409 }));
    wrap();
    expect(await screen.findByRole("alert")).toHaveTextContent("The machine is offline. Try again when it's online.");
  });
});
