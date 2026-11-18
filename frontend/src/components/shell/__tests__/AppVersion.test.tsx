import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppVersion } from "@/components/shell/AppVersion";

function renderVersion(updates: object, { status = 200, className }: { status?: number; className?: string } = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(updates), { status })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppVersion className={className} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AppVersion", () => {
  it("shows a release as v0.23.1, linked to its notes in a new tab", async () => {
    renderVersion({ app_version: "0.23.1", app: null, runner: null });
    const link = await screen.findByRole("link", { name: "MegooColab 0.23.1, release notes (opens in a new tab)" });
    expect(link).toHaveAttribute("href", "https://github.com/mmhy2003/MegooColab/releases/tag/v0.23.1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(link).toHaveTextContent("v0.23.1");
  });

  it("does not double the v of a version that has one", async () => {
    renderVersion({ app_version: "v0.23.1", app: null, runner: null });
    const link = await screen.findByRole("link");
    expect(link.textContent).toBe("v0.23.1");
  });

  it("shows a build from source as plain text, without a link", async () => {
    renderVersion({ app_version: "dev", app: null, runner: null });
    const el = (await screen.findByText("dev")).closest("[title]") as HTMLElement;
    expect(screen.queryByRole("link")).toBeNull();
    expect(el).toHaveAttribute("title", "dev");
    expect(el.textContent).toBe("MegooColab dev");
  });

  it("shows nothing when the server does not say its version", async () => {
    const { container } = renderVersion({ app: null, runner: null });
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when the request fails", async () => {
    const { container } = renderVersion({ detail: "boom" }, { status: 500 });
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it("puts the caller's className on the link", async () => {
    renderVersion({ app_version: "0.23.1", app: null, runner: null }, { className: "ml-auto" });
    expect(await screen.findByRole("link")).toHaveClass("ml-auto");
  });
});
