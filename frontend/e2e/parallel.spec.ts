import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Runs at once: one agent on a real runner works on three chats at the same time, each in its own session and
 * worktree, after its limit is raised on its card; lowering the limit leaves the runs going. Needs the Go toolchain
 * and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = "Parallel agent";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
// every chat's first run thinks for a minute, so all three are going at once
const SCENARIO = [onPrompt(BRAINSTORM, say("Thinking it over"), { sleep_ms: 60_000 })];

type Agent = { id: string; name: string; status: string; running?: number; max_concurrent_runs: number };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json().catch(() => null)) as T;
}

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

test("an agent works on three chats at once, and its limit can be raised and lowered", async ({ page }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-parallel-"));
  let runner: RunnerHandle | undefined;
  let agentId: string | undefined;
  try {
    await setupOrSignIn(page);
    const request = page.request;
    const me = ((await (await request.get("/api/auth/me")).json()) as { user: { id: string } }).user.id;
    const team = await post<{ id: string }>(request, "/api/teams", { name: "Parallel Team", description: "" });
    expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
    await post(request, "/api/projects", { key: "PAR", name: "Parallel Demo", description: "", team_ids: [team.id] });
    const bins = buildBinaries(join(work, "bin"));
    const repo = join(work, "repo");
    mkdirSync(repo);
    git(repo, "init", "-q");
    writeFileSync(join(repo, "README.md"), "# parallel\n");
    git(repo, "add", ".");
    git(repo, "commit", "-q", "-m", "init");
    const agent = await post<Agent>(request, "/api/agents", { program: "claude_code", name: AGENT_NAME });
    agentId = agent.id;
    expect(agent.max_concurrent_runs).toBe(1);
    const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
      data: { bindings: [{ project_ref: "PAR", local_path: repo }] },
      headers: WEB,
    });
    expect(bound.ok(), await bound.text()).toBeTruthy();
    const token = await mintLinkedRunnerToken(request, agent.id, "parallel-e2e-machine");
    runner = startRunner({ url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner });
    const mine = async () => ((await (await request.get("/api/agents/mine")).json()) as Agent[]).find((a) => a.id === agent.id)!;
    await expect.poll(async () => (await mine()).status, { timeout: 20_000 }).toBe("online");

    // 1. one at a time: the first chat runs, the other two wait
    for (const message of ["First thing", "Second thing", "Third thing"]) {
      await post(request, "/api/chats", { project_key: "PAR", agent_id: agent.id, message });
    }
    await expect.poll(async () => (await mine()).running, { timeout: 30_000 }).toBe(1);
    await page.goto("/settings/agents");
    const card = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: AGENT_NAME }) });
    await expect(card.getByText("1 of 1 running")).toBeVisible();
    await expect(card.getByText("Busy")).toBeVisible();

    // 2. raised to 3 on the card: the two waiting chats start at once
    const runs = card.getByLabel("Runs at once", { exact: true });
    await expect(runs).toHaveValue("1");
    await card.getByRole("button", { name: "More runs at once" }).click();
    await card.getByRole("button", { name: "More runs at once" }).click();
    await card.getByRole("button", { name: "Save runs at once" }).click();
    await expect(card.getByText("3 of 3 running")).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("Busy")).toBeVisible();

    // 3. lowered to 1 while all three run: they keep going, and the card says so
    await card.getByLabel("Runs at once", { exact: true }).fill("1");
    await card.getByRole("button", { name: "Save runs at once" }).click();
    await expect(card.getByText("3 running, limit 1")).toBeVisible();
    await expect(card.getByText("3 runs are going now. They finish as they are; nothing new starts until they have finished.")).toBeVisible();
    expect((await mine()).running).toBe(3);
  } finally {
    // deleting the project stops its runs and drops its chats' workflows, which would keep the agent
    await page.request.delete("/api/projects/PAR", { headers: WEB });
    await runner?.stop();
    // later specs expect the admin's agents and machines as they left them
    if (agentId) {
      const id = agentId;
      await expect
        .poll(async () => {
          const r = await page.request.delete(`/api/agents/${id}`, { headers: WEB });
          return `${r.status()} ${await r.text()}`;
        }, { timeout: 30_000 })
        .toMatch(/^204/);
    }
    const tokens = (await (await page.request.get("/api/tokens")).json()) as { id: string; name: string }[];
    for (const t of tokens.filter((x) => x.name === "parallel-e2e-machine")) {
      await page.request.delete(`/api/tokens/${t.id}`, { headers: WEB });
    }
    rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
