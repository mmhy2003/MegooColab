import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TelegramConnect } from "@/components/notifications/TelegramConnect";

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function show(fetchMock: ReturnType<typeof vi.fn<Fetch>>) {
  vi.stubGlobal("fetch", fetchMock);
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TelegramConnect />
    </QueryClientProvider>,
  );
}

describe("TelegramConnect", () => {
  it("hidden without a bot", async () => {
    const fetchMock = vi.fn<Fetch>(async () => json({ available: false, bot_username: null, linked: false }));
    const { container } = show(fetchMock);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("connect opens the Start link and waits", async () => {
    let linked = false;
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const fetchMock = vi.fn<Fetch>(async (url, init) => {
      if (url === "/api/me/telegram/link" && init?.method === "POST") return json({ url: "https://t.me/megoo_bot?start=abc" });
      return json({ available: true, bot_username: "megoo_bot", linked });
    });
    show(fetchMock);
    await userEvent.click(await screen.findByRole("button", { name: "Connect Telegram" }));
    expect(open).toHaveBeenCalledWith("https://t.me/megoo_bot?start=abc", "_blank", "noopener");
    expect(screen.getByText("Waiting for you to press Start in Telegram…")).toBeInTheDocument();
    linked = true;
    expect(await screen.findByText("Connected to Telegram", {}, { timeout: 5_000 })).toBeInTheDocument();
  });

  it("disconnect", async () => {
    const fetchMock = vi.fn<Fetch>(async (_url, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json({ available: true, bot_username: "megoo_bot", linked: true }),
    );
    show(fetchMock);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Telegram" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, init]) => u === "/api/me/telegram" && init?.method === "DELETE")).toBe(true));
  });
});
