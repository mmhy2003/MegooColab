import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WebhookDialog } from "@/components/project/WebhookDialog";
import type { Repo } from "@/lib/types";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const REPO = {
  id: "r1", name: "acme/web", url: "https://github.com/acme/web", provider: "github", default_branch: "develop",
  connection: { id: "c1", name: "GitHub" }, webhook_status: "not_set_up", webhook_last_at: null, warning: null,
} as Repo;
const INFO = {
  url: "https://colab.acme.io/api/git/webhooks/repos/r1", kind: "github",
  hook_page_url: "https://github.com/acme/web/settings/hooks", status: "not_set_up", last_at: null,
  installed: false, public_url_is_default: false,
};

function show(info = INFO, handler?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const own = handler?.(url, init);
    if (own) return own;
    if (url.endsWith("/webhook")) return json(info);
    if (url.endsWith("/webhook/secret") && !init?.method) return json({ secret: "s3cret-one" });
    if (url.endsWith("/webhook/secret")) return json({ secret: "s3cret-two", host_updated: null });
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WebhookDialog projectKey="PAY" repo={REPO} onClose={() => {}} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WebhookDialog", () => {
  it("shows the address, hides the secret until Show, and copies both", async () => {
    const fetchMock = show();
    const dialog = await screen.findByRole("dialog", { name: "Webhook for acme/web" });
    expect(await within(dialog).findByDisplayValue(INFO.url)).toBeInTheDocument();
    expect(within(dialog).queryByDisplayValue("s3cret-one")).toBeNull();
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/webhook/secret") && !i?.method)).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Show" }));
    expect(await within(dialog).findByDisplayValue("s3cret-one")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: /Copy/ }).length).toBeGreaterThanOrEqual(2);
  });

  it("makes a new secret only after a confirmation, and says whether the host was updated", async () => {
    const fetchMock = show({ ...INFO, installed: true }, (url, init) =>
      url.endsWith("/webhook/secret") && init?.method === "POST" ? json({ secret: "s3cret-two", host_updated: true }) : undefined,
    );
    const dialog = await screen.findByRole("dialog", { name: "Webhook for acme/web" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Make a new one" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm).toHaveTextContent("The old secret stops working at once.");
    fireEvent.click(within(confirm).getByRole("button", { name: "Make a new one" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/webhook/secret") && i?.method === "POST")).toBe(true));
    expect(await within(dialog).findByText("Updated on GitHub too.")).toBeInTheDocument();
  });

  it("shows the steps for the repository's host", async () => {
    show({ ...INFO, kind: "gitlab", hook_page_url: "https://lab.acme.io/acme/web/-/hooks" });
    const dialog = await screen.findByRole("dialog", { name: "Webhook for acme/web" });
    expect(await within(dialog).findByText(/Secret token/)).toBeInTheDocument();
    expect(within(dialog).getAllByText(/Merge request events/).length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("link", { name: /Open GitLab's webhook page/ })).toHaveAttribute("href", "https://lab.acme.io/acme/web/-/hooks");
  });

  it("Create it for me says when the token can't", async () => {
    show(INFO, (url, init) => (url.endsWith("/webhook/install") && init?.method === "POST" ? json({ detail: "forbidden" }, 422) : undefined));
    const dialog = await screen.findByRole("dialog", { name: "Webhook for acme/web" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Create it for me" }));
    expect(await within(dialog).findByText(/This token can't manage webhooks/)).toBeInTheDocument();
  });

  it("warns when the public address is the default", async () => {
    show({ ...INFO, url: "http://localhost:8080/api/git/webhooks/repos/r1", public_url_is_default: true });
    const dialog = await screen.findByRole("dialog", { name: "Webhook for acme/web" });
    expect(await within(dialog).findByText(/GitHub and GitLab can't reach/)).toBeInTheDocument();
  });
});
