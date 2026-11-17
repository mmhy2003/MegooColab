import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/agents",
}));

import AdminAgentsPage from "@/app/(app)/admin/agents/page";
import { run } from "@/components/dashboard/__tests__/fixture";

const AGENT = {
  id: "a1", name: "Mo's Claude Code", program: "claude_code", model: null, effort: null, status: "online",
  owner: { id: "u1", name: "Mo" }, machine: null, runner: null, running: 0, max_concurrent_runs: 3, runs: [],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage(agents: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      new Response(JSON.stringify(url === "/api/auth/me" ? { user: { id: "u1", role: "admin" } } : agents), { status: 200 }),
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminAgentsPage />
    </QueryClientProvider>,
  );
}

const row = async () => (await screen.findByText("Mo's Claude Code")).closest("tr")!;

describe("admin agents", () => {
  it("on phones each agent is a card with labelled values", async () => {
    renderPage([AGENT]);
    const cell = (await screen.findByText("Mo's Claude Code")).closest("td")!;
    const table = cell.closest("table")!;
    expect(table).toHaveClass("max-md:block");
    expect(table.querySelector("thead")).toHaveClass("max-md:hidden");
    const labels = Array.from(cell.closest("tr")!.querySelectorAll("td")).map((td) => td.getAttribute("data-label"));
    expect(labels).toEqual(["Owner", "Agent", "Program", "Status", "Working on"]);
  });

  it("lists the newest run and opens the rest", async () => {
    const user = userEvent.setup();
    const runs = [
      run(),
      run({ run_id: "r2", kind: "chat", title: "Pricing ideas", task_key: null, chat_id: "c1", link: "/chats/c1", stage: null }),
      run({ run_id: "r3", kind: "question", title: null, task_key: null, question_key: "PAY-Q12", link: "/questions/q1", stage: null }),
    ];
    renderPage([{ ...AGENT, status: "busy", running: 3, runs }]);
    const tr = await row();
    expect(within(tr).getByText("3 of 3 running")).toBeInTheDocument();
    expect(within(tr).getAllByRole("link").map((a) => a.textContent)).toEqual(["PAY-14"]);
    await user.click(within(tr).getByRole("button", { name: "+2 more" }));
    expect(within(tr).getAllByRole("link")).toHaveLength(3);
    await user.click(within(tr).getByRole("button", { name: "Show less" }));
    expect(within(tr).getAllByRole("link")).toHaveLength(1);
  });

  it("an agent with no runs shows a dash under Working on", async () => {
    renderPage([AGENT]);
    const cell = (await row()).querySelector('td[data-label="Working on"]')!;
    expect(cell).toHaveTextContent("—");
    expect(within(await row()).queryByText(/running/)).toBeNull();
  });
});
