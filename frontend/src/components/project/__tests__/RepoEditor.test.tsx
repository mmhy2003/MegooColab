import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RepoEditor } from "@/components/project/RepoEditor";
import type { Repo } from "@/lib/types";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const repo = (over: Partial<Repo>): Repo =>
  ({ id: "r1", name: "acme/pay", url: "https://github.com/acme/pay", provider: "github", default_branch: "main",
     connection: { id: "c1", name: "GitHub" }, webhook_status: "not_set_up", webhook_last_at: null, warning: null, ...over }) as Repo;

function show(repos: Repo[]) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) =>
    url === "/api/git/connections" ? json([{ id: "c1", name: "GitHub", kind: "github" }]) : json({}),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RepoEditor projectKey="PAY" repos={repos} canEdit onChanged={() => {}} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RepoEditor", () => {
  it("each connected repository shows its webhook status", () => {
    show([
      repo({}),
      repo({ id: "r2", name: "acme/web", webhook_status: "working", webhook_last_at: new Date(Date.now() - 120_000).toISOString() }),
      repo({ id: "r3", name: "acme/old", webhook_status: "failing" }),
      repo({ id: "r4", name: "plain/p", provider: "plain", connection: null }),
    ]);
    const row = (name: string) => screen.getByText(name).closest("li")!;
    expect(within(row("acme/pay")).getByText("Webhook not set up")).toBeInTheDocument();
    expect(within(row("acme/pay")).getByRole("button", { name: "Set up webhook" })).toBeInTheDocument();
    expect(within(row("acme/web")).getByText(/Webhook working · last event .* ago/)).toBeInTheDocument();
    expect(within(row("acme/old")).getByText("Webhook failing")).toBeInTheDocument();
    expect(within(row("plain/p")).queryByText(/Webhook/)).toBeNull();
  });

  it("enter by hand still takes a connection", async () => {
    const fetchMock = show([]);
    fireEvent.click(screen.getByRole("button", { name: "Enter it by hand" }));
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "acme/side" } });
    fireEvent.change(screen.getByLabelText("Repository URL"), { target: { value: "https://github.com/acme/side" } });
    await screen.findAllByRole("option", { name: "GitHub" });
    fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "c1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(JSON.parse(String(init!.body))).toMatchObject({ name: "acme/side", connection_id: "c1" });
  });
});
