import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ key: "PAY", triggerId: "t1" }),
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/projects/PAY/triggers",
  useSearchParams: () => new URLSearchParams(),
}));

import TriggerPage from "@/app/(app)/projects/[key]/triggers/[triggerId]/page";
import { TriggerEditor } from "@/components/triggers/TriggerEditor";
import { TriggerList } from "@/components/triggers/TriggerList";
import { EVENTS } from "@/lib/triggers";

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
let trigger: unknown = TRIGGER;
let firings: unknown[] = [];
let role = "manager";
let sprintsEnabled = true;
let webhookStatus = "not_set_up";
let calls: { url: string; method: string; body?: unknown }[] = [];

beforeEach(() => {
  triggers = [TRIGGER, MOVED, CRONNED];
  trigger = TRIGGER;
  firings = [];
  role = "manager";
  sprintsEnabled = true;
  webhookStatus = "not_set_up";
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.endsWith("/columns")) return new Response(JSON.stringify([{ id: "col1", name: "Ready", position: 1, category: "todo", task_count: 0 }]), { status: 200 });
    if (url.endsWith("/labels")) return new Response(JSON.stringify([{ id: "l1", name: "backend", color: "#fff" }]), { status: 200 });
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "Mia", role } }), { status: 200 });
    if (url === "/api/projects/PAY") return new Response(JSON.stringify({ key: "PAY", name: "Payments", status: "active", sprints_enabled: sprintsEnabled }), { status: 200 });
    if (url.endsWith("/agents")) return new Response(JSON.stringify([
      { id: "a1", name: "laptop", can_use: true }, { id: "a2", name: "not mine", can_use: false },
    ]), { status: 200 });
    if (url.endsWith("/repositories")) return new Response(JSON.stringify([{ id: "r1", name: "payments", webhook_status: webhookStatus }]), { status: 200 });
    if (url.endsWith("/crons")) return new Response(JSON.stringify([{ id: "c1", name: "Nightly deps" }]), { status: 200 });
    if (method === "POST" || method === "PATCH") return new Response(JSON.stringify(TRIGGER), { status: 200 });
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (url.endsWith("/triggers/t1/firings")) return new Response(JSON.stringify(firings), { status: 200 });
    if (url.endsWith("/triggers/t1")) {
      if (trigger === null) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
      return new Response(JSON.stringify(trigger), { status: 200 });
    }
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

describe("TriggerEditor", () => {
  const when = () => screen.getByLabelText("When") as HTMLSelectElement;
  const choose = (event: string) => fireEvent.change(when(), { target: { value: event } });
  const fill = () => {
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: " Triage " } });
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: " Triage it. " } });
  };
  const save = () => screen.getByRole("button", { name: "Save trigger" });
  const sent = (method: string) => calls.find((c) => c.method === method && c.url.startsWith("/api/projects/PAY/triggers"));

  it("TriggerEditor shows the right fields for each event", async () => {
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: "New trigger · PAY" })).toBeInTheDocument();
    await screen.findByRole("option", { name: "A sprint is started" });
    expect([...when().options].map((o) => o.value)).toEqual(EVENTS.map((e) => e.id));
    expect([...when().querySelectorAll("optgroup")].map((g) => g.label))
      .toEqual(["Task events", "Sprint events", "Chains and larger events"]);
    for (const e of EVENTS) {
      choose(e.id);
      const has = (f: string) => e.fields.includes(f as never);
      expect(screen.queryByLabelText("Story") !== null).toBe(has("types"));
      expect(screen.queryByLabelText("Label") !== null).toBe(has("types"));
      expect(screen.queryByLabelText("Column") !== null).toBe(has("column"));
      expect(screen.queryByLabelText("Cron") !== null).toBe(has("cron"));
      expect(screen.queryByText(/Needs the repository's own webhook/) !== null).toBe(has("webhook"));
      expect(screen.getByText("What happened (added under your prompt)")).toBeInTheDocument();
      expect(document.querySelector("pre")).toHaveTextContent(e.example.split("\n")[0]);
    }
  });

  it("hides the sprint events without sprints", async () => {
    sprintsEnabled = false;
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/projects/PAY")).toBe(true));
    await waitFor(() => expect([...when().options].map((o) => o.value)).toEqual(
      EVENTS.filter((e) => !e.sprints).map((e) => e.id)));
    expect(when().querySelector("optgroup[label='Sprint events']")).toBeNull();
  });

  it("posts the body for task_moved", async () => {
    const onClose = vi.fn();
    wrap(<TriggerEditor projectKey="PAY" onClose={onClose} />);
    fill();
    choose("task_moved");
    await screen.findByRole("option", { name: "Ready" });
    expect(save()).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Column"), { target: { value: "col1" } });
    fireEvent.click(screen.getByLabelText("Task"));
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "l1" } });
    await screen.findByRole("option", { name: "laptop" });
    expect(screen.queryByRole("option", { name: "not mine" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Keep the chat open"));
    fireEvent.click(screen.getByLabelText("When the agent replies"));
    fireEvent.click(save());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(sent("POST")).toEqual({
      url: "/api/projects/PAY/triggers", method: "POST", body: {
        name: "Triage", event: "task_moved", config: { task_types: ["story", "bug"], label_id: "l1", column_id: "col1" },
        prompt: "Triage it.", keep_open: true, notify_reply: false, notify_problems: true, agent_id: null,
      },
    });
  });

  it("posts cron_found with any cron", async () => {
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    fill();
    choose("cron_found");
    expect(await screen.findByRole("option", { name: "Nightly deps" })).toBeInTheDocument();
    expect(screen.getByLabelText("Cron")).toHaveValue("");
    expect(screen.getByLabelText("End the chat")).toBeChecked();
    fireEvent.click(save());
    await waitFor(() => expect(sent("POST")).toBeTruthy());
    expect(sent("POST")!.body).toEqual({
      name: "Triage", event: "cron_found", config: { cron_id: null }, prompt: "Triage it.",
      keep_open: false, notify_reply: true, notify_problems: true, agent_id: null,
    });
  });

  it("pr_merged shows the webhook note", async () => {
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    choose("pr_merged");
    expect(await screen.findByText(/nothing fires until it is set up/)).toBeInTheDocument();
    cleanup();
    webhookStatus = "working";
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    choose("pr_merged");
    expect(await screen.findByText(/It is set up/)).toBeInTheDocument();
    expect(screen.queryByText(/nothing fires until it is set up/)).not.toBeInTheDocument();
  });

  it("edit sends a PATCH without agent_id when unchanged", async () => {
    const onClose = vi.fn();
    wrap(<TriggerEditor projectKey="PAY" trigger={{ ...MOVED, any_agent: false, agent: { id: "a2", name: "not mine" } } as never}
      onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "Edit Triage" })).toBeInTheDocument();
    expect(screen.getByText("Saving makes you the person it runs as.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Triage");
    expect(screen.getByLabelText("Story")).not.toBeChecked();
    expect(screen.getByLabelText("Bug")).toBeChecked();
    await screen.findByRole("option", { name: "Ready" });
    expect(screen.getByLabelText("Column")).toHaveValue("col1");
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Triage it now." } });
    fireEvent.click(save());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const patch = sent("PATCH")!;
    expect(patch.url).toBe("/api/projects/PAY/triggers/t2");
    expect(patch.body).toEqual({
      name: "Triage", event: "task_moved", config: { task_types: ["bug"], label_id: null, column_id: "col1" },
      prompt: "Triage it now.", keep_open: false, notify_reply: true, notify_problems: true,
    });
  });

  it("can't save with no type ticked", async () => {
    wrap(<TriggerEditor projectKey="PAY" onClose={() => {}} />);
    fill();
    expect(save()).toBeEnabled();
    for (const t of ["Story", "Task", "Bug"]) fireEvent.click(screen.getByLabelText(t));
    expect(save()).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Bug"));
    expect(save()).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "  " } });
    expect(save()).toBeDisabled();
  });
});

describe("TriggerPage", () => {
  const SKIPPED = {
    ...FIRING, id: "f2", created_at: "2026-11-20T11:00:00Z", chat_id: null, agent: null, result: "skipped", excerpt: "no_agent",
    subject: { kind: "task", label: "PAY-14", title: "Export CSV", link: "/projects/PAY/tasks/14", note: "finished" },
  };

  it("the trigger page shows firings and links to their chats", async () => {
    firings = [FIRING, SKIPPED];
    trigger = { ...TRIGGER, paused: true, broken: "label_deleted", agent: { id: "a1", name: "laptop" }, any_agent: false };
    wrap(<TriggerPage />);
    expect(await screen.findByRole("heading", { name: "Release notes" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Triggers" })).toHaveAttribute("href", "/projects/PAY/triggers");
    expect(screen.getByText("A task is finished")).toBeInTheDocument();
    expect(await screen.findByText("story, task, bug · label backend")).toBeInTheDocument();
    expect(screen.getByText("Runs as Mia")).toBeInTheDocument();
    expect(screen.getByText("Agent: laptop")).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Broken: its label was deleted")).toHaveClass("text-pink");
    expect(document.querySelector("pre")).toHaveTextContent("Write the release notes. Then more.");

    const table = await screen.findByRole("table");
    expect([...table.querySelectorAll("th")].map((h) => h.textContent)).toEqual(["Fired at", "What happened", "Agent", "Result"]);
    const [, replied, skipped] = within(table).getAllByRole("row");
    expect(within(replied).getByText(new Date(FIRING.created_at).toLocaleString())).toBeInTheDocument();
    expect(within(replied).getByRole("link", { name: /PAY-12/ })).toHaveAttribute("href", "/projects/PAY/tasks/12");
    expect(within(replied).getByText(/Fix login/)).toBeInTheDocument();
    expect(within(replied).getByText("finished")).toBeInTheDocument();
    expect(within(replied).getByText("laptop")).toBeInTheDocument();
    expect(within(replied).getByRole("link", { name: "Replied" })).toHaveAttribute("href", "/chats/ch1");
    expect(within(replied).getByText("Done.")).toBeInTheDocument();
    expect(within(skipped).getByText("—")).toBeInTheDocument();
    expect(within(skipped).getByText("Skipped")).toBeInTheDocument();
    expect(within(skipped).queryByRole("link", { name: "Skipped" })).not.toBeInTheDocument();
    expect(within(skipped).getByText("No agent can take it")).toBeInTheDocument();
  });

  it("says when there are no firings, and any free agent", async () => {
    wrap(<TriggerPage />);
    expect(await screen.findByText("No firings yet.")).toBeInTheDocument();
    expect(screen.getByText("Agent: any free agent")).toBeInTheDocument();
  });

  it("shows not found on a 404", async () => {
    trigger = null;
    wrap(<TriggerPage />);
    expect(await screen.findByText("This page doesn't exist")).toBeInTheDocument();
  });

  it("Try it posts and is hidden for pr_merged or with no try_subject", async () => {
    wrap(<TriggerPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Try it on PAY-12" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/triggers/t1/try")).toBe(true));
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.url === "/api/projects/PAY/triggers/t1/firings").length).toBeGreaterThan(1));
    cleanup();

    trigger = { ...TRIGGER, event: "pr_merged", config: {} };
    wrap(<TriggerPage />);
    await screen.findByRole("button", { name: "Edit" });
    expect(screen.queryByRole("button", { name: /Try it/ })).not.toBeInTheDocument();
    cleanup();

    trigger = { ...TRIGGER, try_subject: null };
    wrap(<TriggerPage />);
    await screen.findByRole("button", { name: "Edit" });
    expect(screen.queryByRole("button", { name: /Try it/ })).not.toBeInTheDocument();
  });

  it("pauses, resumes and edits", async () => {
    wrap(<TriggerPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/triggers/t1/pause")).toBe(true));
    cleanup();
    trigger = { ...TRIGGER, paused: true };
    wrap(<TriggerPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/triggers/t1/resume")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("dialog", { name: "Edit Release notes" })).toBeInTheDocument();
  });

  it("delete asks first", async () => {
    wrap(<TriggerPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete Release notes?" });
    expect(dialog).toHaveTextContent("Its firings go with it. The chats it started stay.");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete trigger" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/PAY/triggers"));
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/projects/PAY/triggers/t1")).toBe(true);
  });

  it("members see no buttons", async () => {
    role = "member";
    firings = [FIRING];
    wrap(<TriggerPage />);
    await screen.findByRole("table");
    expect(screen.getByRole("heading", { name: "Release notes" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
