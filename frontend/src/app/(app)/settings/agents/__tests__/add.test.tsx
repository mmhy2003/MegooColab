import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/settings/agents" }));

import AgentsPage from "@/app/(app)/settings/agents/page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Add agent", () => {
  it("starts a new agent on its program's default model, which can be changed", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response("[]"));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AgentsPage />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add agent" }));
    const model = screen.getByLabelText("Model");
    expect(model).toHaveValue("Opus 5.5");
    await userEvent.selectOptions(screen.getByLabelText("Program"), "codex");
    expect(model).toHaveValue("GPT-6.1 Sol");
    expect(screen.getByLabelText("Effort")).toHaveValue("");
    await userEvent.selectOptions(screen.getByLabelText("Effort"), "high");
    await userEvent.clear(model);
    await userEvent.type(model, "gpt-6.1-sol-mini");
    await userEvent.click(screen.getAllByRole("button", { name: "Add agent" }).at(-1)!);
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([u, init]) => u === "/api/agents" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ program: "codex", model: "gpt-6.1-sol-mini", effort: "high" });
    });
  });

  it("an OMP agent starts on the program's own default model", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response("[]"));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AgentsPage />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add agent" }));
    await userEvent.selectOptions(screen.getByLabelText("Program"), "omp");
    expect(screen.getByLabelText("Model")).toHaveValue("");
    await userEvent.click(screen.getAllByRole("button", { name: "Add agent" }).at(-1)!);
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([u, init]) => u === "/api/agents" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ program: "omp", model: null });
    });
  });

  it("an emptied model asks for the program's own default", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response("[]"));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AgentsPage />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add agent" }));
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.click(screen.getAllByRole("button", { name: "Add agent" }).at(-1)!);
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([u, init]) => u === "/api/agents" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ model: null, effort: null });
    });
  });
});

describe("Runs at once", () => {
  function renderPage(agents: unknown[] = []) {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url, init) => {
      if (url === "/api/agents/mine") return new Response(JSON.stringify(agents));
      if (init?.method === "PATCH") return new Response(JSON.stringify(agents[0]));
      return new Response("[]");
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AgentsPage />
      </QueryClientProvider>,
    );
    return fetchMock;
  }

  it("a new agent starts at one, and can be given more", async () => {
    const fetchMock = renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Add agent" }));
    expect(screen.getByLabelText("Runs at once")).toHaveValue(1);
    await userEvent.click(screen.getByRole("button", { name: "More runs at once" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Add agent" }).at(-1)!);
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([u, init]) => u === "/api/agents" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ max_concurrent_runs: 2 });
    });
  });

  it("an agent's card shows how many run, and saves a new limit", async () => {
    const agent = {
      id: "a1", name: "My Claude Code", program: "claude_code", answer_mode: "manual", max_concurrent_runs: 3,
      running: 1, status: "online", problems: [], bindings: [], owner: { id: "u1", name: "Me", email: "me@x.io" },
      model: null, effort: null, known_models: [],
    };
    const fetchMock = renderPage([agent]);
    expect(await screen.findByText("1 of 3 running")).toBeInTheDocument();
    expect(screen.getByLabelText("Runs at once")).toHaveValue(3);
    await userEvent.click(screen.getByRole("button", { name: "Fewer runs at once" }));
    await userEvent.click(screen.getByRole("button", { name: "Save runs at once" }));
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([u, init]) => u === "/api/agents/a1" && init?.method === "PATCH");
      expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ max_concurrent_runs: 2 });
    });
  });
});
