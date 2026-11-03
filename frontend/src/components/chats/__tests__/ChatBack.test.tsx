import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = { push: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ChatBack } from "@/components/chats/ChatBack";
import { recordVisit } from "@/lib/backNav";

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function back() {
  render(<ChatBack fallback="/chats" />);
  await userEvent.click(screen.getByRole("button", { name: "All chats" }));
}

describe("ChatBack", () => {
  it("back without history goes to all chats", async () => {
    await back();
    expect(router.push).toHaveBeenCalledWith("/chats");
  });

  it("back from a project's chat list goes back to it, after moving inside the app", async () => {
    // the pages this tab showed, as the app's recorder notes them on each client-side move
    recordVisit("/projects/AUD/chats", "Chats");
    recordVisit("/chats/c1", "Fix the button");
    await back();
    expect(router.push).toHaveBeenCalledWith("/projects/AUD/chats");
  });

  it("moving from one chat to another keeps the list it started from", async () => {
    recordVisit("/projects/AUD/chats", "Chats");
    recordVisit("/chats/c1", "Fix the button");
    recordVisit("/chats/c2", "Another");
    await back();
    expect(router.push).toHaveBeenCalledWith("/projects/AUD/chats");
  });

  it("a chat opened from anywhere else goes to all chats", async () => {
    recordVisit("/notifications", "Notifications");
    recordVisit("/chats/c1", "Fix the button");
    await back();
    expect(router.push).toHaveBeenCalledWith("/chats");
  });

  it("never relies on the browser's history, which a new tab doesn't have", async () => {
    recordVisit("/chats", "Chats");
    recordVisit("/chats/c1", "Fix the button");
    await back();
    expect(router.push).toHaveBeenCalledWith("/chats");
    expect(router.back).not.toHaveBeenCalled();
  });
});
