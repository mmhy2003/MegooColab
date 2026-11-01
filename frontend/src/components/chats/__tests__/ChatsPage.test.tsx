import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/PAY/chats",
  useSearchParams: () => new URLSearchParams(),
}));

import { ChatsPage } from "@/components/chats/ChatsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatsPage", () => {
  it("opens the New chat dialog from a project's tab", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatsPage projectKey="PAY" />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "New chat" }));
    expect(await screen.findByRole("dialog", { name: "New chat" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeVisible();
  });
});
