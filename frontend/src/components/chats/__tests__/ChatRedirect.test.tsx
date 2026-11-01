import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { ChatRedirect } from "@/components/chats/ChatRedirect";

afterEach(cleanup);

describe("ChatRedirect", () => {
  it("redirects a chat round's task page to the chat", () => {
    render(<ChatRedirect chatId="c1" />);
    expect(replace).toHaveBeenCalledWith("/chats/c1");
    expect(screen.getByRole("link", { name: "Open the chat" })).toHaveAttribute("href", "/chats/c1");
  });
});
