import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSettingsPage from "@/app/(app)/admin/settings/page";
import { GitConnections } from "@/components/git/GitConnections";
import { PullRequestBadge } from "@/components/git/PullRequestBadge";
import { RepoEditor } from "@/components/project/RepoEditor";
import { WorkflowPanel } from "@/components/workflow/WorkflowPanel";
import type { Repo, Workflow } from "@/lib/types";

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init) ?? new Response("[]", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const sent = (fetchMock: ReturnType<typeof mockFetch>, method: string) =>
  fetchMock.mock.calls.filter(([, i]) => i?.method === method).map(([u, i]) => ({ url: u, body: JSON.parse(String(i!.body ?? "null")) }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const GHE = { id: "c1", name: "GHE", kind: "github", base_url: "https://ghe.example", token_set: true, webhook_secret_set: true };

describe("GitConnections", () => {
  it("creates, tests and never shows the token", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/git-connections" && !init?.method) return json([GHE]);
      if (url === "/api/admin/git-connections" && init?.method === "POST") return json({ ...GHE, id: "c2", name: "Lab", kind: "gitlab" }, 201);
      if (url === "/api/admin/git-connections/c1/test") return json({ ok: true, login: "octocat" });
      if (url === "/api/admin/git-connections/c1" && init?.method === "PATCH") return json(GHE);
      return undefined;
    });
    wrap(<GitConnections />);
    const row = (await screen.findByText("GHE")).closest("li")!;
    expect((within(row).getByLabelText("Webhook URL") as HTMLInputElement).value).toMatch(/\/api\/git\/webhooks\/c1$/);
    fireEvent.click(within(row).getByRole("button", { name: "Test" }));
    expect(await within(row).findByText("Connected as octocat")).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const token = screen.getByLabelText("Token") as HTMLInputElement;
    expect(token.value).toBe("");
    expect(token).toHaveAttribute("placeholder", "••••");
    expect(token).toHaveAttribute("type", "password");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GHE 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PATCH")).toHaveLength(1));
    expect(sent(fetchMock, "PATCH")[0].body).toEqual({ name: "GHE 2", base_url: "https://ghe.example" }); // no token: kept

    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Lab" } });
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "gitlab" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://gitlab.example" } });
    fireEvent.change(screen.getByLabelText("Token"), { target: { value: "glpat-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "POST").some((c) => c.url === "/api/admin/git-connections")).toBe(true));
    expect(sent(fetchMock, "POST").find((c) => c.url === "/api/admin/git-connections")!.body).toEqual({
      name: "Lab", kind: "gitlab", base_url: "https://gitlab.example", token: "glpat-secret", webhook_secret: "",
    });
    expect(screen.queryByDisplayValue("glpat-secret")).toBeNull(); // the form closed and forgot it
  });
});

describe("PullRequestBadge", () => {
  const pr = (extra: object) => ({ url: "https://github.com/o/r/pull/1", state: "open", checks: "none", review: "none", tracked: true, ...extra });

  it("states and checks", () => {
    const cases: [object, string][] = [
      [{ checks: "pending" }, "PR open · checks pending"],
      [{ checks: "success" }, "PR open · checks passed"],
      [{ checks: "failure", review: "changes_requested" }, "PR open · checks failed · changes requested"],
      [{ review: "approved" }, "PR open · approved"],
      [{ state: "merged", checks: "success" }, "PR merged"],
      [{ state: "closed" }, "PR closed"],
      [{ tracked: false }, "PR (not tracked)"],
    ];
    for (const [extra, text] of cases) {
      const { unmount } = render(<PullRequestBadge pr={pr(extra)} />);
      const link = screen.getByRole("link");
      expect(link).toHaveTextContent(text);
      expect(link).toHaveAttribute("href", "https://github.com/o/r/pull/1");
      unmount();
    }
  });
});

describe("RepoEditor", () => {
  it("Repository connection select saves", async () => {
    const repo = { id: "r1", name: "pay", url: "https://ghe.example/o/pay", provider: "github", default_branch: "main", connection: null } as unknown as Repo;
    const fetchMock = mockFetch((url) => {
      if (url === "/api/git/connections") return json([{ id: "c1", name: "GHE" }]);
      return undefined;
    });
    const onChanged = vi.fn();
    wrap(<RepoEditor projectKey="PAY" repos={[repo]} onChanged={onChanged} />);
    const select = await screen.findByRole("combobox", { name: "Connection for pay" });
    await within(select).findByRole("option", { name: "GHE" });
    expect(select).toHaveValue("");
    fireEvent.change(select, { target: { value: "c1" } });
    await waitFor(() => expect(sent(fetchMock, "PATCH")).toEqual([{ url: "/api/projects/PAY/repositories/r1", body: { connection_id: "c1" } }]));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
});

describe("WorkflowPanel", () => {
  it("shows Mark merged while waiting on human code review", async () => {
    const workflow = {
      driver: "runner", stage: "done", status: "waiting_human", needs: "human_code_review", enforcement: "enforced",
      current_step: null, steps_total: null, escalation_reason: null, can_act: true, finishing_option: "pull_request",
      finishing_forced: false, can_set_manual: false, branch: "megoo/pay-1", pr_url: "https://github.com/o/r/pull/1",
      documents: [], open_question_id: null, steps: [],
      pull_request: { url: "https://github.com/o/r/pull/1", state: "open", checks: "pending", review: "none", tracked: true },
    } as unknown as Workflow;
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "POST") return json(workflow);
      if (url.includes("/agent-runs")) return json([]);
      return json(workflow);
    });
    wrap(<WorkflowPanel taskKey="PAY-1" />);
    expect(await screen.findByText("PR open · checks pending")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve PR" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mark merged" }));
    await waitFor(() => expect(sent(fetchMock, "POST")).toEqual([{ url: "/api/tasks/PAY-1/workflow/human-review", body: { approved: true } }]));
  });
});

describe("Admin settings", () => {
  it("save dreaming and defaults", async () => {
    const settings = {
      name: "Acme",
      smtp: { host: null, port: null, user: null, from: null, tls: true, password_set: false },
      dreaming: { enabled: true, hour_utc: null },
      project_defaults: { finishing_option: "pull_request", require_human_code_review: false, sprints_enabled: true, commit_docs_to_repo: false },
    };
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/settings" && !init?.method) return json(settings);
      if (url === "/api/admin/settings" && init?.method === "PUT") return json(settings);
      return undefined;
    });
    wrap(<AdminSettingsPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Run dreaming every night" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Run dreaming every night" }));
    fireEvent.change(screen.getByLabelText("Dreaming hour (UTC)"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Default finishing option"), { target: { value: "keep_branch" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Require a human code review" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Sprints" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT")).toHaveLength(1));
    const body = sent(fetchMock, "PUT")[0].body;
    expect(body.dreaming).toEqual({ enabled: true, hour_utc: 5 });
    expect(body.project_defaults).toEqual({
      finishing_option: "keep_branch", require_human_code_review: true, sprints_enabled: false, commit_docs_to_repo: false,
    });
    fireEvent.change(screen.getByLabelText("Dreaming hour (UTC)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT")).toHaveLength(2));
    expect(sent(fetchMock, "PUT")[1].body.dreaming).toEqual({ enabled: true, hour_utc: null }); // empty: the server setting
  });
});
