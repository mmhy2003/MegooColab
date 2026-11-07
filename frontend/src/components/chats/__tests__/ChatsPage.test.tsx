import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function page(props: { projectKey?: string; chatId?: string }) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatsPage {...props} />
    </QueryClientProvider>,
  );
}

describe("ChatsPage", () => {
  it("on a phone an open chat hides the page intro", async () => {
    const { container } = page({ chatId: "c1" });
    const heading = await screen.findByRole("heading", { level: 1, name: "Chats" });
    expect(heading.closest("[class~='max-md:hidden']")).not.toBeNull();
    expect(container.querySelector('a[href="/chats"]')).toBeNull(); // the old "← All chats" link
  });

  it("the grid has a single shrinking column on phones", () => {
    const { container } = page({});
    expect(container.querySelector(".grid")).toHaveClass("grid-cols-[minmax(0,1fr)]");
  });

  it("a project's chat list has its own Chats header row with New chat", async () => {
    page({ projectKey: "PAY" });
    expect(await screen.findByRole("heading", { name: "Chats" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat" })).toBeInTheDocument();
  });

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

  it("scrolls the chat list on its own, under the project filter", async () => {
    const chats = [{ id: "c1", project_key: "PAY", title: "Fix empty email", state: "talking", can_act: true, rounds: [] }];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/api/chats") ? chats : []), { status: 200 })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChatsPage />
      </QueryClientProvider>,
    );
    const list = await screen.findByRole("list");
    expect(list.closest(".overflow-y-auto")).not.toBeNull();
    expect(screen.getByLabelText("Project").closest(".overflow-y-auto")).toBeNull();
  });
});

describe("ChatsPage filters", () => {
  beforeEach(() => window.localStorage.clear());
  const CHATS = [
    { id: "c1", project_key: "PAY", title: "Asks", status: "open", state: "question", can_act: true, rounds: [] },
    { id: "c2", project_key: "PAY", title: "Builds", status: "open", state: "building", can_act: true, rounds: [] },
    { id: "c3", project_key: "PAY", title: "Talks", status: "open", state: "talking", can_act: true, rounds: [] },
    { id: "c4", project_key: "PAY", title: "Away", status: "open", state: "offline", can_act: true, rounds: [] },
    { id: "c5", project_key: "PAY", title: "Done", status: "ended", state: "ended", can_act: true, rounds: [] },
    { id: "c6", project_key: "PAY", title: "Older", status: "ended", state: "ended", can_act: true, rounds: [] },
  ];
  function show() {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/api/chats") ? CHATS : []), { status: 200 })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ChatsPage />
      </QueryClientProvider>,
    );
  }
  const chip = (name: RegExp) => within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name });

  it("shows the active chats first, with a count on each filter", async () => {
    show();
    await screen.findByText("Asks");
    expect(chip(/^Active/)).toHaveAttribute("aria-pressed", "true");
    expect(chip(/^All/)).toHaveTextContent("6");
    expect(chip(/^Active/)).toHaveTextContent("4");
    expect(chip(/^Needs you/)).toHaveTextContent("1");
    expect(chip(/^Working/)).toHaveTextContent("1");
    expect(chip(/^Open/)).toHaveTextContent("2"); // offline counts as open
    expect(chip(/^Ended/)).toHaveTextContent("2");
    expect(screen.queryByText("Done")).toBeNull();
    expect(screen.getByText("Away")).toBeInTheDocument();
  });

  it("filters to one group, and remembers it", async () => {
    const { unmount } = show();
    await screen.findByText("Asks");
    fireEvent.click(chip(/^Ended/));
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.queryByText("Asks")).toBeNull();
    unmount();
    show();
    expect(await screen.findByText("Older")).toBeInTheDocument();
    expect(chip(/^Ended/)).toHaveAttribute("aria-pressed", "true");
  });

  it("says so when a filter leaves nothing", async () => {
    CHATS.splice(0, 1);
    try {
      show();
      await screen.findByText("Builds");
      fireEvent.click(chip(/^Needs you/));
      expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
    } finally {
      CHATS.unshift({ id: "c1", project_key: "PAY", title: "Asks", status: "open", state: "question", can_act: true, rounds: [] });
    }
  });
});
