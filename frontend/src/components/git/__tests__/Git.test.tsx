import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const GHE = {
  id: "c1", name: "GHE", kind: "github", base_url: "https://ghe.example", hosted: false, token_set: true,
  webhook_secret_set: false, waiting_repositories: [],
};

const kind = (name: string) => within(screen.getByRole("group", { name: "Kind" })).getByRole("button", { name });
const where = (name: string) => within(screen.getByRole("group", { name: "Where" })).getByRole("button", { name });

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
    expect(within(row).queryByLabelText("Webhook URL")).toBeNull(); // each repository has its own now
    fireEvent.click(within(row).getByRole("button", { name: "Test" }));
    expect(await within(row).findByText("Connected as octocat")).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const token = screen.getByLabelText("Access token") as HTMLInputElement;
    expect(token.value).toBe("");
    expect(token).toHaveAttribute("placeholder", "••••");
    expect(token).toHaveAttribute("type", "password");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GHE 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PATCH")).toHaveLength(1));
    expect(sent(fetchMock, "PATCH")[0].body).toEqual({ name: "GHE 2", base_url: "https://ghe.example" }); // no token: kept

    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Lab" } });
    fireEvent.click(kind("GitLab"));
    fireEvent.click(where("Self-hosted"));
    fireEvent.change(screen.getByLabelText("Server address"), { target: { value: "https://gitlab.example" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "glpat-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "POST").some((c) => c.url === "/api/admin/git-connections")).toBe(true));
    expect(sent(fetchMock, "POST").find((c) => c.url === "/api/admin/git-connections")!.body).toEqual({
      name: "Lab", kind: "gitlab", base_url: "https://gitlab.example", token: "glpat-secret",
    });
    expect(screen.queryByDisplayValue("glpat-secret")).toBeNull(); // the form closed and forgot it
  });

  it("asks for a server address only when self-hosted, and never for a webhook secret", async () => {
    mockFetch((url) => (url === "/api/admin/git-connections" ? json([]) : undefined));
    wrap(<GitConnections />);
    fireEvent.click(await screen.findByRole("button", { name: "Add connection" }));
    expect(kind("GitHub")).toHaveAttribute("aria-pressed", "true");
    expect(where("GitHub.com")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText("Server address")).toBeNull();
    expect(screen.queryByLabelText(/Webhook secret/)).toBeNull();
    fireEvent.click(where("Self-hosted"));
    expect(screen.getByLabelText("Server address")).toBeInTheDocument();
    fireEvent.click(kind("Gitea / Forgejo"));
    expect(screen.queryByRole("group", { name: "Where" })).toBeNull(); // always self-hosted
    expect(screen.getByLabelText("Server address")).toBeInTheDocument();
  });

  it("a hosted provider sends no address", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/git-connections" && !init?.method) return json([]);
      if (init?.method === "POST") return json({ ...GHE, id: "c3" }, 201);
      return undefined;
    });
    wrap(<GitConnections />);
    fireEvent.click(await screen.findByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GitHub" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "ghp_x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "POST")).toHaveLength(1));
    expect(sent(fetchMock, "POST")[0].body).toEqual({ name: "GitHub", kind: "github", token: "ghp_x" });
  });

  describe("what the token needs", () => {
    const open = async () => {
      mockFetch((url) => (url === "/api/admin/git-connections" ? json([]) : undefined));
      wrap(<GitConnections />);
      fireEvent.click(await screen.findByRole("button", { name: "Add connection" }));
      return screen.getByRole("region", { name: "What the token needs" });
    };
    const row = (card: HTMLElement, why: string) => within(card).getByText(why).closest("li")!;

    it("lays GitHub's out one reason a row, each permission its own chip, with its access", async () => {
      const card = await open();
      const follow = row(card, "Follow pull requests");
      expect(follow).toHaveTextContent("Required");
      for (const p of ["Contents", "Metadata", "Pull requests", "Commit statuses"]) {
        expect(within(follow).getByText(p).closest("li")).toHaveTextContent(`${p}Read`);
      }
      expect(follow).toHaveTextContent("A fine-grained token can't read check runs");
      expect(row(card, "Set up webhooks in one click")).toHaveTextContent("Optional");
      expect(row(card, "Set up webhooks in one click")).toHaveTextContent("WebhooksRead and write");
      expect(row(card, "Let an agent review and merge")).toHaveTextContent("Pull requestsRead and write");
      expect(within(card).getByRole("link", { name: "Create a token on GitHub" })).toHaveAttribute(
        "href", "https://github.com/settings/personal-access-tokens/new",
      );
      expect(within(card).getByRole("link", { name: "GitHub's guide" })).toHaveAttribute("href", expect.stringContaining("docs.github.com"));
    });

    it("switches GitHub to a classic token's scopes, without the check-runs note", async () => {
      const card = await open();
      const type = within(card).getByRole("group", { name: "Token type" });
      expect(within(type).getByRole("button", { name: "Fine-grained token" })).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(within(type).getByRole("button", { name: "Classic token" }));
      expect(row(card, "Follow pull requests")).toHaveTextContent("repo");
      expect(card).not.toHaveTextContent("A fine-grained token can't read check runs");
      expect(row(card, "Set up webhooks in one click")).toHaveTextContent("admin:repo_hook");
      expect(within(card).getByRole("link", { name: "Create a classic token on GitHub" })).toHaveAttribute(
        "href", "https://github.com/settings/tokens/new?description=MegooColab&scopes=repo",
      );
    });

    it("uses each host's own words, with no token type to pick", async () => {
      const card = await open();
      fireEvent.click(kind("GitLab"));
      expect(within(card).queryByRole("group", { name: "Token type" })).toBeNull();
      expect(row(card, "Follow merge requests")).toHaveTextContent("read_api");
      expect(within(card).getByRole("link", { name: "Create a token on GitLab" })).toHaveAttribute(
        "href", "https://gitlab.com/-/user_settings/personal_access_tokens?name=MegooColab&scopes=read_api",
      );
      fireEvent.click(kind("Gitea / Forgejo"));
      expect(row(card, "Follow pull requests")).toHaveTextContent("read:repository");
    });

    it("links a self-hosted server's own new-token page, once its address is in", async () => {
      const card = await open();
      fireEvent.click(where("Self-hosted"));
      expect(within(card).queryByRole("link", { name: "Create a token on GitHub" })).toBeNull();
      fireEvent.change(screen.getByLabelText("Server address"), { target: { value: "https://ghe.example.com/" } });
      expect(within(card).getByRole("link", { name: "Create a token on GitHub" })).toHaveAttribute(
        "href", "https://ghe.example.com/settings/personal-access-tokens/new",
      );
    });
  });

  it("a provider with the old shared secret lists the repositories still on it and asks before removing it", async () => {
    const old = { ...GHE, webhook_secret_set: true, waiting_repositories: [{ project_key: "PAY", name: "acme/pay" }] };
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/admin/git-connections" && !init?.method) return json([old]);
      if (init?.method === "PATCH") return json({ ...old, webhook_secret_set: false, waiting_repositories: [] });
      return undefined;
    });
    wrap(<GitConnections />);
    const row = (await screen.findByText("GHE")).closest("li")!;
    expect(within(row).getByText(/still has a shared webhook secret/)).toBeInTheDocument();
    expect(within(row).getByText("PAY · acme/pay")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Remove shared secret" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm).toHaveTextContent(/would stop getting updates/);
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(sent(fetchMock, "PATCH")).toHaveLength(1));
    expect(sent(fetchMock, "PATCH")[0].body).toEqual({ webhook_secret: "" });
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

  it("an unreadable pull request says so, in pink, with the reason in its title and name", () => {
    render(<PullRequestBadge pr={pr({ error: "forbidden", host: "github" })} />);
    const reason = "GitHub refused the token (forbidden). It needs Pull requests and Commit statuses (read).";
    const link = screen.getByRole("link", { name: new RegExp("can't read.*GitHub refused the token") });
    expect(link).toHaveTextContent("PR · can't read");
    expect(link).toHaveAttribute("title", reason);
    expect(link.className).toContain("border-pink");
  });

  it("a partial read keeps the state and explains what is unknown", () => {
    render(<PullRequestBadge pr={pr({ checks: "unknown", limited: "checks", host: "github" })} />);
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent("PR open · checks unknown");
    expect(link).toHaveAttribute("title", "Checks unknown: GitHub doesn't let a fine-grained token read check runs, where GitHub Actions reports. A classic token with repo shows them.");
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
    wrap(<RepoEditor projectKey="PAY" repos={[repo]} canEdit onChanged={onChanged} />);
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
