import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminAiPage from "@/app/(app)/admin/ai/page";

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/admin/ai",
  useSearchParams: () => new URLSearchParams(search),
}));

const SETTINGS = {
  name: "Acme",
  smtp: { host: null, port: null, user: null, from: null, tls: true, password_set: false },
  dreaming: { enabled: true, hour_utc: null },
  project_defaults: { finishing_option: "pull_request", require_human_code_review: false, sprints_enabled: true, commit_docs_to_repo: false },
};

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
const puts = () =>
  fetchMock.mock.calls.filter(([, i]) => i?.method === "PUT").map(([u, i]) => ({ url: u, body: JSON.parse(String(i?.body)) }));

beforeEach(() => {
  search = "";
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "A", email: "a@x.io", role: "admin" } }));
    if (url === "/api/admin/settings") return new Response(JSON.stringify(SETTINGS));
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminAiPage />
    </QueryClientProvider>,
  );

describe("AI page in tabs", () => {
  it("has four tabs, Providers first", async () => {
    renderPage();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Providers", "Models per job", "Dreaming", "Usage"]);
    expect(screen.getByRole("tab", { name: "Providers" })).toHaveAttribute("aria-selected", "true");
  });

  it("Dreaming holds the nightly schedule, moved from Settings, beside Dream now", async () => {
    search = "tab=dreaming";
    renderPage();
    const panel = within(await screen.findByRole("tabpanel", { name: "Dreaming" }));
    fireEvent.click(await panel.findByRole("checkbox", { name: "Run dreaming every night" }));
    fireEvent.click(panel.getByRole("checkbox", { name: "Run dreaming every night" }));
    fireEvent.change(panel.getByLabelText("Dreaming hour (UTC)"), { target: { value: "5" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({
      url: "/api/admin/settings",
      body: {
        name: "Acme",
        smtp: { host: null, port: null, user: null, from: null, tls: true, password: null },
        dreaming: { enabled: true, hour_utc: 5 },
      },
    });
    fireEvent.change(panel.getByLabelText("Dreaming hour (UTC)"), { target: { value: "" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1].body.dreaming).toEqual({ enabled: true, hour_utc: null }); // empty: the server's setting
    expect(panel.getByRole("button", { name: "Dream now" })).toBeInTheDocument();
  });
});
