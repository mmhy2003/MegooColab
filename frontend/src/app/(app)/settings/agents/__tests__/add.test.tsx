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
