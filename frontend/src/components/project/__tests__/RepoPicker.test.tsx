import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RepoPicker } from "@/components/project/RepoPicker";

const CONNECTIONS = [{ id: "c1", name: "Acme GitLab", kind: "gitlab" }];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function show(choices: (url: string) => Response) {
  const fetchMock = vi.fn(async (url: string) => (url === "/api/git/connections" ? json(CONNECTIONS) : choices(url)));
  vi.stubGlobal("fetch", fetchMock);
  const onPick = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RepoPicker projectKey="PAY" onPick={onPick} />
    </QueryClientProvider>,
  );
  return { fetchMock, onPick };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("RepoPicker", () => {
  it("lists the provider's repositories, searches as you type, and picking fills the form", async () => {
    const { fetchMock, onPick } = show((url) =>
      json({
        items: url.includes("q=check")
          ? [{ path: "platform/checkout-service", url: "https://lab.acme.io/platform/checkout-service", default_branch: "main" }]
          : [{ path: "platform/api", url: "https://lab.acme.io/platform/api", default_branch: "develop" }],
        more: false,
      }),
    );
    await screen.findByRole("option", { name: "Acme GitLab" });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "c1" } });
    // the first page shows without typing
    expect(await screen.findByRole("button", { name: /platform\/api/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Repository"), { target: { value: "check" } });
    const pick = await screen.findByRole("button", { name: /platform\/checkout-service/ }, { timeout: 2000 });
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/projects/PAY/repositories/choices?connection_id=c1&q=check"))).toBe(true);
    fireEvent.click(pick);
    expect(onPick).toHaveBeenCalledWith({
      connectionId: "c1", kind: "gitlab", path: "platform/checkout-service",
      url: "https://lab.acme.io/platform/checkout-service", defaultBranch: "main",
    });
  });

  it("shows the provider's refusal in plain words", async () => {
    show(() => json({ detail: "unauthorized" }, 502));
    await screen.findByRole("option", { name: "Acme GitLab" });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "c1" } });
    expect(await screen.findByText("The git host refused the token.")).toBeInTheDocument();
  });

  it("loads more while the provider has more", async () => {
    show((url) =>
      json(url.includes("page=2")
        ? { items: [{ path: "o/second", url: "https://x/o/second", default_branch: null }], more: false }
        : { items: [{ path: "o/first", url: "https://x/o/first", default_branch: "main" }], more: true }),
    );
    await screen.findByRole("option", { name: "Acme GitLab" });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "c1" } });
    await screen.findByRole("button", { name: /o\/first/ });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Load more" })));
    await waitFor(() => expect(screen.getByRole("button", { name: /o\/second/ })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });
});
