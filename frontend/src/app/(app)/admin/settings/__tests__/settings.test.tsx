import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSettingsPage from "@/app/(app)/admin/settings/page";

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/admin/settings",
  useSearchParams: () => new URLSearchParams(search),
}));

const SETTINGS = {
  name: "Acme",
  smtp: { host: "smtp.acme.io", port: 587, user: "megoo", from: "megoo@acme.io", tls: true, password_set: true },
  dreaming: { enabled: true, hour_utc: 3 },
  project_defaults: { finishing_option: "pull_request", require_human_code_review: false, sprints_enabled: true, commit_docs_to_repo: false },
};
const KEPT_SMTP = { host: "smtp.acme.io", port: 587, user: "megoo", from: "megoo@acme.io", tls: true, password: null };

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
const puts = () =>
  fetchMock.mock.calls.filter(([, i]) => i?.method === "PUT").map(([u, i]) => ({ url: u, body: JSON.parse(String(i?.body)) }));

beforeEach(() => {
  search = "";
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/admin/settings") return new Response(JSON.stringify(SETTINGS));
    if (url === "/api/admin/search") return new Response(JSON.stringify({ available: true, documents: 12, last_rebuild_at: null }));
    if (url === "/api/admin/rate-limits") return new Response(JSON.stringify({ valkey: true, limits: [] }));
    return new Response(null, { status: 204 });
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
      <AdminSettingsPage />
    </QueryClientProvider>,
  );

describe("Admin settings in tabs", () => {
  it("has five tabs, General first, and no dreaming hour", async () => {
    renderPage();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["General", "Email", "New projects", "Search", "Rate limits"]);
    expect(await screen.findByLabelText("Organization name")).toBeVisible();
    expect(screen.getByLabelText("Host")).not.toBeVisible();
    expect(screen.queryByLabelText("Dreaming hour (UTC)")).toBeNull(); // moved to AI → Dreaming
  });

  it("General saves the name only, keeping the email settings", async () => {
    renderPage();
    const panel = within(await screen.findByRole("tabpanel", { name: "General" }));
    fireEvent.change(panel.getByLabelText("Organization name"), { target: { value: "Acme Corp" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({ url: "/api/admin/settings", body: { name: "Acme Corp", smtp: KEPT_SMTP } });
    expect(await panel.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("Email saves the mail settings, and the test email sits with them", async () => {
    search = "tab=email";
    renderPage();
    const panel = within(await screen.findByRole("tabpanel", { name: "Email" }));
    fireEvent.change(panel.getByLabelText("Host"), { target: { value: "mail.acme.io" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ name: "Acme", smtp: { ...KEPT_SMTP, host: "mail.acme.io" } });
    expect(panel.getByLabelText("Send a test email to")).toBeInTheDocument();
  });

  it("New projects saves the defaults only", async () => {
    search = "tab=new-projects";
    renderPage();
    const panel = within(await screen.findByRole("tabpanel", { name: "New projects" }));
    fireEvent.change(panel.getByLabelText("Default finishing option"), { target: { value: "keep_branch" } });
    fireEvent.click(panel.getByRole("checkbox", { name: "Require a human code review" }));
    fireEvent.click(panel.getByRole("checkbox", { name: "Sprints" }));
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      name: "Acme",
      smtp: KEPT_SMTP,
      project_defaults: { finishing_option: "keep_branch", require_human_code_review: true, sprints_enabled: false, commit_docs_to_repo: false },
    });
  });

  it("Search and Rate limits have their own tabs", async () => {
    search = "tab=search";
    renderPage();
    expect(await screen.findByRole("tabpanel", { name: "Search" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Rate limits" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1); // the other tabs' panels are hidden
  });
});
