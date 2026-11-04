import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SecretsPanel } from "@/components/secrets/SecretsPanel";

const SECRETS = [
  { id: "s1", name: "STAGING_DB_PASSWORD", description: "Staging Postgres password", updated_at: "2026-11-04T10:00:00Z",
    value_updated_at: "2026-11-04T10:00:00Z", updated_by: { id: "u1", name: "Ann" } },
];

function renderPanel({ canEdit = true, outdated = [] as { id: string; name: string }[], project = undefined as string | undefined } = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.includes("outdated-agents")) return new Response(JSON.stringify(outdated), { status: 200 });
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (method === "GET") return new Response(JSON.stringify(SECRETS), { status: 200 });
    return new Response(JSON.stringify(SECRETS[0]), { status: method === "POST" ? 201 : 200 });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const base = project ? `/api/projects/${project}/secrets` : "/api/secrets";
  render(
    <QueryClientProvider client={client}>
      <SecretsPanel base={base} canEdit={canEdit} project={project} />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SecretsPanel", () => {
  it("lists names and descriptions, the value only as dots", async () => {
    renderPanel();
    expect(await screen.findByText("STAGING_DB_PASSWORD")).toBeInTheDocument();
    expect(screen.getByText("Staging Postgres password")).toBeInTheDocument();
    expect(screen.getAllByText("••••••••").length).toBeGreaterThan(0);
    expect(screen.getByText(/by Ann/)).toBeInTheDocument();
  });

  it("adds a secret, checking the name as it is typed", async () => {
    const calls = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Add secret" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Environment variable name"), { target: { value: "lower_case" } });
    expect(within(dialog).getByText("Capital letters, digits and _, starting with a letter")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Save secret" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Environment variable name"), { target: { value: "API_KEY" } });
    fireEvent.change(within(dialog).getByLabelText("What it is (the agent reads this)"), { target: { value: "Our API key" } });
    fireEvent.change(within(dialog).getByLabelText("Value"), { target: { value: "abc" } });
    expect(within(dialog).getByText("Values shorter than 4 characters can't be blanked out of what agents send back.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Value"), { target: { value: "abcd-1234" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save secret" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "API_KEY", description: "Our API key", value: "abcd-1234",
    }));
  });

  it("replaces only the value, and deletes after a confirmation", async () => {
    const calls = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Replace value" }));
    fireEvent.change(within(screen.getByRole("dialog")).getByLabelText("Value"), { target: { value: "new-value-1" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save value" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")).toEqual({
      url: "/api/secrets/s1/value", method: "PUT", body: { value: "new-value-1" },
    }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/Agents stop getting it on their next run/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete secret" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/secrets/s1")).toBe(true));
  });

  it("shows no buttons to someone who can't edit", async () => {
    renderPanel({ canEdit: false, project: "PAY" });
    await screen.findByText("STAGING_DB_PASSWORD");
    expect(screen.queryByRole("button", { name: "Add secret" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replace value" })).not.toBeInTheDocument();
    expect(screen.getByText(/Every agent that works on this project gets these as environment variables/)).toBeInTheDocument();
  });

  it("names the agents whose runner is too old", async () => {
    renderPanel({ outdated: [{ id: "a1", name: "old-bot" }] });
    expect(await screen.findByText(/These agents' runners are too old to get secrets: old-bot/)).toBeInTheDocument();
  });
});
