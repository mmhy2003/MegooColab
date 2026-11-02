import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TelegramForm } from "@/components/admin/TelegramForm";

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(fetchMock: ReturnType<typeof vi.fn<Fetch>>) {
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TelegramForm />
    </QueryClientProvider>,
  );
}

describe("TelegramForm", () => {
  it("saves a token and shows the bot", async () => {
    let bot: string | null = null;
    const fetchMock = vi.fn<Fetch>(async (_url, init) => {
      if (init?.method === "PUT") bot = "megoo_bot";
      return new Response(JSON.stringify({ bot_username: bot }));
    });
    show(fetchMock);
    await userEvent.type(await screen.findByLabelText("Bot token"), "42:SECRET");
    expect(screen.getByText("In Telegram, open @BotFather and send /newbot.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Connected to @megoo_bot.")).toBeInTheDocument();
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(put[0]).toBe("/api/admin/telegram");
    expect(JSON.parse(String(put[1]?.body))).toEqual({ token: "42:SECRET" });
  });

  it("shows why a token was refused", async () => {
    show(vi.fn<Fetch>(async (_url, init) =>
      init?.method === "PUT"
        ? new Response(JSON.stringify({ detail: "telegram_token_refused" }), { status: 422 })
        : new Response(JSON.stringify({ bot_username: null })),
    ));
    await userEvent.type(await screen.findByLabelText("Bot token"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Telegram doesn't accept this token");
  });

  it("removes the bot after asking", async () => {
    const fetchMock = vi.fn<Fetch>(async (_url, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : new Response(JSON.stringify({ bot_username: "megoo_bot" })),
    );
    show(fetchMock);
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    const confirm = screen.getByRole("alertdialog", { name: "Remove the bot?" });
    expect(confirm).toHaveTextContent("Telegram notifications stop for everyone.");
    await userEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, init]) => u === "/api/admin/telegram" && init?.method === "DELETE")).toBe(true));
  });
});
