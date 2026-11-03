import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { push: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ChatBack } from "@/components/chats/ChatBack";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

function referrer(value: string) {
  Object.defineProperty(document, "referrer", { configurable: true, value });
}

describe("ChatBack", () => {
  it("back without history goes to all chats", async () => {
    referrer("");
    render(<ChatBack fallback="/chats" />);
    await userEvent.click(screen.getByRole("button", { name: "All chats" }));
    expect(router.push).toHaveBeenCalledWith("/chats");
    expect(router.back).not.toHaveBeenCalled();
  });

  it("back from a project's chat list goes back", async () => {
    referrer(`${window.location.origin}/projects/AUD/chats`);
    render(<ChatBack fallback="/chats" />);
    await userEvent.click(screen.getByRole("button", { name: "All chats" }));
    expect(router.back).toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("a link from another site does not count as the list", async () => {
    referrer("https://elsewhere.example/chats");
    render(<ChatBack fallback="/chats" />);
    await userEvent.click(screen.getByRole("button", { name: "All chats" }));
    expect(router.push).toHaveBeenCalledWith("/chats");
  });
});
