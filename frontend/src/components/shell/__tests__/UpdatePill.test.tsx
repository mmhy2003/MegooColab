import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpdatePill } from "@/components/shell/UpdatePill";

const RELEASE = "https://github.com/mmhy2003/MegooColab/releases/tag/v0.2.0";

function renderPill(updates: object) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(updates), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <UpdatePill />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UpdatePill", () => {
  it("says a newer MegooColab is out, with what's new and how to update", async () => {
    renderPill({ app: { current: "0.1.0", latest: "0.2.0", url: RELEASE }, runner: null });
    const pill = await screen.findByRole("button", { name: "Update available: MegooColab 0.2.0" });
    expect(pill).toHaveTextContent("Update");
    await userEvent.click(pill);
    expect(screen.getByText("MegooColab 0.2.0")).toBeInTheDocument();
    expect(screen.getByText("You're on 0.1.0.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "What's new" })).toHaveAttribute("href", RELEASE);
    expect(screen.getByRole("link", { name: "How to update" })).toHaveAttribute(
      "href", "https://github.com/mmhy2003/MegooColab/blob/main/docs/install.md#12-upgrades",
    );
  });

  it("is not there when the server is up to date (or the viewer is not an admin)", async () => {
    renderPill({ app: null, runner: { latest: "0.1.0", url: "x" } });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button")).toBeNull();
  });
});
