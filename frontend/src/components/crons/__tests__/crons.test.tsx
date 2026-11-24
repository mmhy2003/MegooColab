import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/projects/PAY/crons",
  useSearchParams: () => new URLSearchParams(),
}));

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { CATALOG_ID } from "@/components/a2ui/catalog";
import { CronEditor } from "@/components/crons/CronEditor";
import { CronList } from "@/components/crons/CronList";
import { CronReport } from "@/components/crons/CronReport";
import { ScheduleField } from "@/components/crons/ScheduleField";

const NEXT = ["2026-11-05T09:00:00Z", "2026-11-06T09:00:00Z", "2026-11-09T09:00:00Z"];
const CRON = {
  id: "c1", project_key: "PAY", name: "Nightly dependency check", prompt: "Check the deps.\nThen more.", schedule: "0 2 * * *",
  timezone: "UTC", description: "At 02:00", agent: null, mode: "tasks", kb_title: null, kb_document_id: null,
  notify_findings: true, notify_every: false, notify_failures: true, paused: false, next_run_at: "2026-11-05T02:00:00Z",
  last_run: { id: "r1", scheduled_at: "2026-11-04T02:00:00Z", status: "skipped", skip_reason: "no_agent_online", agent: null,
    started_at: null, finished_at: null, report: null, commit: null, tasks_created: 0 },
  created_by: null, created_at: "2026-11-01T00:00:00Z",
};

let calls: { url: string; method: string; body?: unknown }[] = [];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === "/api/crons/preview") {
      const bad = (body as { schedule: string }).schedule.includes("25");
      return new Response(JSON.stringify(bad
        ? { ok: false, error: "Hour must be 0–23 (you wrote 25)", description: null, next: [] }
        : { ok: true, error: null, description: "At 09:00, Monday through Friday", next: NEXT }), { status: 200 });
    }
    if (url.endsWith("/agents")) return new Response(JSON.stringify([]), { status: 200 });
    if (url.endsWith("/run-now")) return new Response(JSON.stringify(CRON.last_run), { status: 201 });
    if (method === "POST") return new Response(JSON.stringify(CRON), { status: 201 });
    return new Response(JSON.stringify([CRON]), { status: 200 });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  push.mockReset();
});

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ScheduleField", () => {
  it("fills an expression from a preset and shows it in plain words with the next runs", async () => {
    const onChange = vi.fn();
    wrap(<ScheduleField value="" timezone="UTC" onChange={onChange} onValid={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Weekdays at…" }));
    expect(onChange).toHaveBeenCalledWith("0 9 * * 1-5");
  });

  it("says what is wrong and that the schedule can't be saved", async () => {
    const onValid = vi.fn();
    wrap(<ScheduleField value="0 25 * * *" timezone="UTC" onChange={() => {}} onValid={onValid} />);
    expect(await screen.findByText("Hour must be 0–23 (you wrote 25)")).toBeInTheDocument();
    expect(onValid).toHaveBeenLastCalledWith(false);
    expect(screen.getByText("hour")).toBeInTheDocument(); // the five fields are labelled
  });

  it("words a valid schedule and lists three next runs", async () => {
    const onValid = vi.fn();
    wrap(<ScheduleField value="0 9 * * 1-5" timezone="UTC" onChange={() => {}} onValid={onValid} />);
    expect(await screen.findByText("At 09:00, Monday through Friday")).toBeInTheDocument();
    expect(screen.getByText(/Next runs:/)).toBeInTheDocument();
    expect(onValid).toHaveBeenLastCalledWith(true);
  });
});

describe("CronEditor", () => {
  it("posts the cron, and can't save while the schedule is wrong", async () => {
    wrap(<CronEditor projectKey="PAY" onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Nightly dependency check" } });
    fireEvent.change(within(dialog).getByLabelText("What the agent should do"), { target: { value: "Check the deps." } });
    fireEvent.change(within(dialog).getByLabelText("Schedule"), { target: { value: "0 25 * * *" } });
    await within(dialog).findByText("Hour must be 0–23 (you wrote 25)");
    expect(within(dialog).getByRole("button", { name: "Save cron" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Schedule"), { target: { value: "0 9 * * 1-5" } });
    await within(dialog).findByText("At 09:00, Monday through Friday");
    fireEvent.click(within(dialog).getByLabelText(/Report, and open tasks for real problems/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save cron" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url === "/api/projects/PAY/crons")?.body)
      .toMatchObject({ name: "Nightly dependency check", prompt: "Check the deps.", schedule: "0 9 * * 1-5",
        agent_id: null, mode: "tasks", notify_findings: true, notify_every: false, notify_failures: true }));
  });
});

describe("CronList", () => {
  it("shows when it runs in words and as written, and how the last run went", async () => {
    wrap(<CronList projectKey="PAY" canManage />);
    expect(await screen.findByText("Nightly dependency check")).toBeInTheDocument();
    expect(screen.getByText("At 02:00")).toBeInTheDocument();
    expect(screen.getByText("0 2 * * *")).toBeInTheDocument();
    expect(screen.getByText("skipped: no agent online")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/PAY/crons/c1/run-now")).toBe(true));
  });

  it("shows members no controls", async () => {
    wrap(<CronList projectKey="PAY" canManage={false} />);
    await screen.findByText("Nightly dependency check");
    expect(screen.queryByRole("button", { name: "Run now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New cron" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });
});

describe("CronReport", () => {
  it("links findings to their tasks", () => {
    act(() => {
      wrap(<CronReport projectKey="PAY" run={{ ...CRON.last_run, status: "done", skip_reason: null, commit: "a".repeat(40),
        report: { summary: "2 problems.", findings: [{ title: "jsonwebtoken 8.5.1", detail: "Vulnerable.", task_key: "PAY-88", created: true },
          { title: "sqlalchemy 1.4", detail: "Behind.", task_key: "PAY-61" }], checked: "180 packages", nothing_new: false, notes: [] } } as never} />);
    });
    expect(screen.getByText("2 problems.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PAY-88 created" })).toHaveAttribute("href", "/projects/PAY/tasks/88");
    expect(screen.getByRole("link", { name: "PAY-61" })).toHaveAttribute("href", "/projects/PAY/tasks/61");
    expect(screen.getByText(/aaaaaaa/)).toBeInTheDocument();
  });

  it("says why a run was skipped", () => {
    wrap(<CronReport projectKey="PAY" run={CRON.last_run as never} />);
    expect(screen.getByText("skipped: no agent online")).toBeInTheDocument();
  });

  const example = (
    JSON.parse(readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "panels.json"), "utf8")) as {
      valid: { name: string; panel: { components: Record<string, unknown>[]; data: Record<string, unknown> } }[];
    }
  ).valid.find((p) => p.name === "example")!.panel;
  const PANEL_MESSAGE = {
    version: "1.0",
    createSurface: { surfaceId: "panel-0123456789ab", catalogId: CATALOG_ID, components: example.components, dataModel: example.data },
  };
  const reported = (panel: unknown) => ({
    ...CRON.last_run, status: "done", skip_reason: null, panel,
    report: { summary: "3 failing.", findings: [], checked: "the suite", nothing_new: false, notes: [] },
  }) as never;
  const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;

  it("draws the panel above the summary", async () => {
    wrap(<CronReport projectKey="PAY" run={reported(PANEL_MESSAGE)} />);
    const tile = await screen.findByRole("group", { name: "Failing" });
    const summary = screen.getByRole("heading", { name: "Summary" });
    const panel = screen.getByRole("heading", { name: "Panel" });
    expect(panel.compareDocumentPosition(summary) & FOLLOWING).toBeTruthy();
    expect(tile.compareDocumentPosition(summary) & FOLLOWING).toBeTruthy();
  });

  it("without a panel the run reads as before", () => {
    const { container } = wrap(<CronReport projectKey="PAY" run={reported(null)} />);
    expect(screen.queryByRole("heading", { name: "Panel" })).not.toBeInTheDocument();
    expect(container.querySelector("h3")).toHaveTextContent("Summary");
  });

  it("a panel that can't be drawn leaves the report complete", async () => {
    vi.resetModules();
    vi.doMock("@a2ui/react", () => {
      throw new Error("x");
    });
    try {
      const { CronReport } = await import("@/components/crons/CronReport");
      wrap(<CronReport projectKey="PAY" run={reported(PANEL_MESSAGE)} />);
      expect(
        await screen.findByText("This run's panel couldn't be drawn. The report below is complete without it."),
      ).toBeInTheDocument();
      expect(screen.getByText("3 failing.")).toBeInTheDocument();
    } finally {
      vi.doUnmock("@a2ui/react");
      vi.resetModules();
    }
  });

  it("a run without a report shows no panel", () => {
    wrap(<CronReport projectKey="PAY" run={{ ...CRON.last_run, panel: PANEL_MESSAGE } as never} />);
    expect(screen.queryByRole("heading", { name: "Panel" })).not.toBeInTheDocument();
  });
});

describe("review fixes", () => {
  it("never shows the last expression's meaning, or allows saving, before the new one is checked", async () => {
    const onValid = vi.fn();
    const { rerender } = wrap(<ScheduleField value="0 9 * * 1-5" timezone="UTC" onChange={() => {}} onValid={onValid} />);
    expect(await screen.findByText("At 09:00, Monday through Friday")).toBeInTheDocument();
    onValid.mockClear();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ScheduleField value="0 25 * * *" timezone="UTC" onChange={() => {}} onValid={onValid} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("At 09:00, Monday through Friday")).not.toBeInTheDocument();
    expect(onValid).toHaveBeenCalledWith(false);
  });

  it("an edit that doesn't touch the agent doesn't send it", async () => {
    wrap(<CronEditor projectKey="PAY" cron={{ ...CRON, any_agent: false, agent: { id: "a9", name: "someone-else" } } as never}
      onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("At 09:00, Monday through Friday");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save cron" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")).toBeTruthy());
    expect(calls.find((c) => c.method === "PATCH")!.body).not.toHaveProperty("agent_id");
  });
});
