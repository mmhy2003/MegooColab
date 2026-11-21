import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/projects/PAY/triggers",
  useSearchParams: () => new URLSearchParams(),
}));

import { TriggerList } from "@/components/triggers/TriggerList";

const FIRING = {
  id: "f1", created_at: "2026-11-20T10:00:00Z", agent: { id: "a1", name: "laptop" }, chat_id: "ch1",
  subject: { kind: "task", label: "PAY-12", title: "Fix login", link: "/projects/PAY/tasks/12", note: "finished" },
  result: "replied", excerpt: "Done.",
};
const TRIGGER = {
  id: "t1", project_key: "PAY", name: "Release notes", event: "task_finished",
  config: { task_types: ["story", "task", "bug"], label_id: "l1" }, prompt: "Write the release notes.\nThen more.",
  any_agent: true, agent: null, keep_open: false, notify_reply: true, notify_problems: true, paused: false,
  owner: { id: "u1", name: "Mia" }, created_by: { id: "u1", name: "Mia" },
  created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
  broken: null, last_firing: FIRING, try_subject: "PAY-12",
};
const MOVED = {
  ...TRIGGER, id: "t2", name: "Triage", event: "task_moved", config: { task_types: ["bug"], column_id: "col1" },
  prompt: "Triage it.", paused: true,
  last_firing: { ...FIRING, id: "f2", chat_id: null, agent: null, result: "skipped", excerpt: "no_agent",
    subject: { ...FIRING.subject, label: "PAY-14", note: "moved to Ready" } },
};
const CRONNED = {
  ...TRIGGER, id: "t3", name: "Deps follow-up", event: "cron_found", config: { cron_id: "c1" }, prompt: "Fix the deps.",
  last_firing: null,
};

let triggers: unknown[] = [];
let calls: { url: string; method: string; body?: unknown }[] = [];

beforeEach(() => {
  triggers = [TRIGGER, MOVED, CRONNED];
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.endsWith("/columns")) return new Response(JSON.stringify([{ id: "col1", name: "Ready", position: 1, category: "todo", task_count: 0 }]), { status: 200 });
    if (url.endsWith("/labels")) return new Response(JSON.stringify([{ id: "l1", name: "backend", color: "#fff" }]), { status: 200 });
    if (url.endsWith("/crons")) return new Response(JSON.stringify([{ id: "c1", name: "Nightly deps" }]), { status: 200 });
    if (method === "POST") return new Response(JSON.stringify(TRIGGER), { status: 200 });
    return new Response(JSON.stringify(triggers), { status: 200 });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const row = (name: string) => screen.getByRole("link", { name: new RegExp(name) }).closest("li") as HTMLElement;

describe("TriggerList", () => {
  it("TriggerList shows rows, results and skip texts", async () => {
    wrap(<TriggerList projectKey="PAY" canManage />);
    expect(await screen.findByRole("link", { name: /Release notes/ })).toHaveAttribute("href", "/projects/PAY/triggers/t1");
    const first = row("Release notes");
    expect(within(first).getByText("Write the release notes.")).toBeInTheDocument();
    expect(within(first).getByText("A task is finished")).toBeInTheDocument();
    expect(await within(first).findByText("story, task, bug · label backend")).toBeInTheDocument();
    expect(within(first).getByText(/PAY-12/)).toHaveTextContent("PAY-12 · Replied");

    const second = row("Triage");
    expect(within(second).getByText("A task is moved to a column")).toBeInTheDocument();
    expect(await within(second).findByText("to Ready · bug")).toBeInTheDocument();
    expect(within(second).getByText(/PAY-14/)).toHaveTextContent("PAY-14 · Skipped: No agent can take it");
    expect(within(second).getByText("Paused")).toBeInTheDocument();

    const third = row("Deps follow-up");
    expect(await within(third).findByText("Nightly deps")).toBeInTheDocument();
    expect(within(third).getByText("Not fired yet")).toBeInTheDocument();
    expect(within(first).queryByText("Paused")).not.toBeInTheDocument();
  });

  it("says when there are no triggers", async () => {
    triggers = [];
    wrap(<TriggerList projectKey="PAY" canManage />);
    expect(await screen.findByText("No triggers yet.")).toBeInTheDocument();
  });

  it("TriggerList pauses and resumes", async () => {
    wrap(<TriggerList projectKey="PAY" canManage />);
    await screen.findByRole("link", { name: /Release notes/ });
    fireEvent.click(within(row("Release notes")).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/triggers/t1/pause")).toBe(true));
    fireEvent.click(within(row("Triage")).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/triggers/t2/resume")).toBe(true));
    // the list is read again after each
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.url === "/api/projects/PAY/triggers").length).toBeGreaterThan(1));
  });

  it("shows an error in an alert", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return new Response(JSON.stringify({ detail: "Not allowed" }), { status: 403 });
      return new Response(JSON.stringify(url.endsWith("/triggers") ? [TRIGGER] : []), { status: 200 });
    }));
    wrap(<TriggerList projectKey="PAY" canManage />);
    await screen.findByRole("link", { name: /Release notes/ });
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not allowed");
  });

  it("New trigger opens the editor", async () => {
    wrap(<TriggerList projectKey="PAY" canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "New trigger" }));
    expect(screen.getByRole("dialog", { name: "New trigger · PAY" })).toBeInTheDocument();
  });

  it("members see no controls", async () => {
    wrap(<TriggerList projectKey="PAY" canManage={false} />);
    await screen.findByRole("link", { name: /Release notes/ });
    expect(screen.queryByRole("button", { name: "New trigger" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("a broken trigger says why", async () => {
    triggers = [{ ...MOVED, broken: "column_deleted", config: { task_types: ["bug"], column_id: "gone" } }];
    wrap(<TriggerList projectKey="PAY" canManage />);
    const broken = await screen.findByText("Broken: its column was deleted");
    expect(broken).toHaveClass("text-pink");
  });
});
