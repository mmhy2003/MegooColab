import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * OMP agents (plan 25): an OMP agent on a real runner, with the fake agent standing in for `omp acp`, answers a chat,
 * and a push installs a skill and an MCP server into its OMP agent folder. Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = "OMP e2e agent";
const MACHINE = "omp-e2e-machine";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const SCENARIO = [onPrompt(BRAINSTORM, say("Hello from OMP"), { sleep_ms: 60_000 })];
const KEY = "omp-e2e-secret-246810";

type Agent = { id: string; status: string };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json().catch(() => null)) as T;
}

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

test("an OMP agent answers a chat and gets its hub tools", async ({ page }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-omp-"));
  const home = join(work, "home");
  const agentDir = join(home, ".omp", "agent");
  let runner: RunnerHandle | undefined;
  let agentId: string | undefined;
  try {
    await setupOrSignIn(page);
    const request = page.request;
    const me = ((await (await request.get("/api/auth/me")).json()) as { user: { id: string } }).user.id;
    const team = await post<{ id: string }>(request, "/api/teams", { name: "OMP Team", description: "" });
    expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
    await post(request, "/api/projects", { key: "OMP", name: "OMP Demo", description: "", team_ids: [team.id] });
    const bins = buildBinaries(join(work, "bin"));
    const repo = join(work, "repo");
    mkdirSync(repo);
    git(repo, "init", "-q");
    writeFileSync(join(repo, "README.md"), "# omp\n");
    git(repo, "add", ".");
    git(repo, "commit", "-q", "-m", "init");

    // 1. an OMP agent starts on OMP's own default model
    const agent = await post<Agent & { model: string | null }>(request, "/api/agents", { program: "omp", name: AGENT_NAME });
    agentId = agent.id;
    expect(agent.model).toBeNull();
    const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
      data: { bindings: [{ project_ref: "OMP", local_path: repo }] },
      headers: WEB,
    });
    expect(bound.ok(), await bound.text()).toBeTruthy();
    const token = await mintLinkedRunnerToken(request, agent.id, MACHINE);
    runner = startRunner({
      url: BASE, token, home, adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
      env: { PI_CODING_AGENT_DIR: agentDir, OMP_PROFILE: "", PI_PROFILE: "", PI_CONFIG_DIR: "" },
    });
    await page.goto("/settings/agents");
    const card = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: AGENT_NAME }) });
    await expect(card.getByText("OMP", { exact: true })).toBeVisible();
    await expect(card.getByText("Online")).toBeVisible({ timeout: 20_000 });

    // 2. a chat on it reaches the agent
    const chat = await post<{ id: string }>(request, "/api/chats", { project_key: "OMP", agent_id: agent.id, message: "Say hello" });
    await page.goto(`/chats/${chat.id}`);
    await expect(page.getByRole("main").getByText(`${AGENT_NAME} · OMP`)).toBeVisible();
    await expect(page.getByRole("main").getByText("Hello from OMP")).toBeVisible({ timeout: 30_000 });

    // 3. a pushed MCP server and skill land in the OMP agent folder
    const tool = await post<{ id: string }>(request, "/api/hub/tools", {
      kind: "mcp", name: "omp-docs",
      spec: { transport: "http", url: "https://mcp.example.com/mcp", headers: [{ name: "X-Key", secret: true }] },
    });
    expect((await request.put(`/api/hub/tools/${tool.id}/secrets`, { data: { values: { "X-Key": KEY } }, headers: WEB })).ok()).toBeTruthy();
    const skillMd = "---\nname: omp-ui\ndescription: UI help for OMP\n---\nUse the design system.\n";
    const skill = await request.post("/api/hub/skills", {
      multipart: { files: { name: "omp-ui/SKILL.md", mimeType: "text/markdown", buffer: Buffer.from(skillMd) } },
      headers: WEB,
    });
    expect(skill.ok(), await skill.text()).toBeTruthy();
    await page.goto("/settings/agents");
    const panel = page.getByRole("region", { name: `Tools on "${MACHINE}"` });
    await expect(panel.getByText(/· connected$/)).toBeVisible({ timeout: 30_000 });
    await panel.getByRole("checkbox", { name: "omp-docs" }).check();
    await panel.getByRole("checkbox", { name: "omp-ui" }).check();
    await panel.getByRole("button", { name: "Push 2 changes" }).click();
    await expect(panel.getByText("OMP: installed")).toHaveCount(2, { timeout: 15_000 });
    const mcp = JSON.parse(readFileSync(join(agentDir, "mcp.json"), "utf8")) as {
      mcpServers: Record<string, { type: string; url: string; headers: Record<string, string> }>;
    };
    expect(mcp.mcpServers["omp-docs"]).toEqual({ type: "http", url: "https://mcp.example.com/mcp", headers: { "X-Key": KEY } });
    expect(existsSync(join(agentDir, "skills", "omp-ui", "SKILL.md"))).toBeTruthy();
  } finally {
    // deleting the project stops its runs and drops the chat's workflow, which would keep the agent
    await page.request.delete("/api/projects/OMP", { headers: WEB });
    await runner?.stop();
    // later specs expect the admin's agents and machines as they left them
    if (agentId) {
      const id = agentId;
      await expect
        .poll(async () => (await page.request.delete(`/api/agents/${id}`, { headers: WEB })).status(), { timeout: 30_000 })
        .toBe(204);
    }
    const tokens = (await (await page.request.get("/api/tokens")).json()) as { id: string; name: string }[];
    for (const t of tokens.filter((x) => x.name === MACHINE)) {
      await page.request.delete(`/api/tokens/${t.id}`, { headers: WEB });
    }
    rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
