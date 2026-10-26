import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAiPage from "@/app/(app)/admin/ai/page";
import { JobModels } from "@/components/ai/JobModels";
import { ProviderList } from "@/components/ai/ProviderList";
import { UsageTable } from "@/components/ai/UsageTable";

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    return handler(url, init) ?? new Response("[]", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProviderList", () => {
  it("never shows a key and sends api_key only when replaced", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/ai/providers" && !init?.method) {
        return json([{ id: "p1", name: "OpenAI", kind: "openai", api_base: null, has_key: true }]);
      }
      if (url === "/api/admin/ai/providers/p1" && init?.method === "PATCH") {
        return json({ id: "p1", name: "OpenAI 2", kind: "openai", api_base: null, has_key: true });
      }
      return undefined;
    });
    wrap(<ProviderList />);
    const row = await screen.findByText("OpenAI");
    const item = row.closest("li")!;
    expect(within(item).getByText("Key saved")).toBeInTheDocument();

    fireEvent.click(within(item).getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "OpenAI 2" } });
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(true));
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!;
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ name: "OpenAI 2", kind: "openai", api_base: null });

    fetchMock.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace key" }));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-new" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(true));
    const second = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!;
    expect(JSON.parse(second[1]!.body as string).api_key).toBe("sk-new");
  });

  it("shows why a provider in use cannot be deleted", async () => {
    vi.stubGlobal("confirm", () => true);
    mockFetch((url, init) => {
      if (url === "/api/admin/ai/providers" && !init?.method) {
        return json([{ id: "p1", name: "OpenAI", kind: "openai", api_base: null, has_key: false }]);
      }
      if (init?.method === "DELETE") return json({ detail: "provider_in_use" }, 409);
      return undefined;
    });
    wrap(<ProviderList />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This provider is used by a job");
  });
});

describe("JobModels", () => {
  it("test button shows result", async () => {
    mockFetch((url, init) => {
      if (url === "/api/admin/ai/providers") {
        return json([{ id: "p1", name: "OpenAI", kind: "openai", api_base: null, has_key: true }]);
      }
      if (url === "/api/admin/ai/jobs") return json([{ job: "embeddings", provider_id: "p1", model: "text-embedding-3-small" }]);
      if (url === "/api/admin/ai/jobs/embeddings/test" && init?.method === "POST") {
        return json({ ok: false, model: "openai/text-embedding-3-small", error: "AuthenticationError: bad key" });
      }
      return undefined;
    });
    wrap(<JobModels />);
    expect(await screen.findByDisplayValue("text-embedding-3-small")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByRole("status")).toHaveTextContent("AuthenticationError: bad key");
  });

  it("saves provider and model", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/ai/providers") {
        return json([{ id: "p1", name: "OpenAI", kind: "openai", api_base: null, has_key: true }]);
      }
      if (url === "/api/admin/ai/jobs" ) return json([{ job: "embeddings", provider_id: null, model: "" }]);
      if (init?.method === "PUT") return json({ job: "embeddings", provider_id: "p1", model: "m" });
      return undefined;
    });
    wrap(<JobModels />);
    fireEvent.change(await screen.findByLabelText("Provider"), { target: { value: "p1" } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "m" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(put[0]).toBe("/api/admin/ai/jobs/embeddings");
    expect(JSON.parse(put[1]!.body as string)).toEqual({ provider_id: "p1", model: "m" });
  });
});

describe("UsageTable", () => {
  it("renders totals", async () => {
    mockFetch((url) => {
      if (url.startsWith("/api/admin/ai/usage")) {
        return json([
          { day: "2026-10-26", job: "embeddings", model: "m1", calls: 3, failures: 1, input_tokens: 1200, output_tokens: 0, cost_usd: 0.0123 },
          { day: "2026-10-25", job: "embeddings", model: "m1", calls: 2, failures: 0, input_tokens: 800, output_tokens: 0, cost_usd: null },
        ]);
      }
      return undefined;
    });
    wrap(<UsageTable />);
    expect(await screen.findByText("2026-10-26")).toBeInTheDocument();
    const total = screen.getByText("Total").closest("tr")!;
    expect(within(total).getByText("5")).toBeInTheDocument();
    expect(within(total).getByText("2,000")).toBeInTheDocument();
    expect(within(total).getByText("$0.0123")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // unknown cost
  });
});

describe("AdminAiPage", () => {
  it("non-admin sees forbidden card", async () => {
    mockFetch((url) => (url === "/api/auth/me" ? json({ user: { id: "u1", name: "M", role: "member" } }) : undefined));
    wrap(<AdminAiPage />);
    expect(await screen.findByText(/don't have permission/)).toBeInTheDocument();
  });
});
