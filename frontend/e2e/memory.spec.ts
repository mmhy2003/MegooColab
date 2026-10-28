import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * End-to-end test of Plan 5, the collective memory: AI jobs, learning from a comment (the worker extracts with
 * fake models), deleting a conclusion that is then not re-learned, dreaming (an induced pattern with its
 * reasoning chain and a summary card), asking the memory, scope isolation for another team, and the MCP tools.
 * Needs a fresh stack started with AI_FAKE=true and MEMORY_EXTRACT_DELAY_SECONDS=2 (README "Memory end-to-end
 * test"). Project key MEM.
 */

const WEB = { "X-Megoo-Client": "web" };
const OUTSIDER = { name: "Otto Outside", email: "otto@acme.io", password: "otto-password-1" };
const WEBHOOK_FACT = "The billing service retries webhooks three times with HMAC signatures";
const SIGNED_FACT = "Webhooks are signed with HMAC SHA256 keys";

type Entity = { id: string; kind: string; name: string };
type Conclusion = { id: string; text: string; kind: string; status: string };
type Job = { kind: string; status: string };

async function post<T = unknown>(request: APIRequestContext, url: string, data?: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

async function get<T = unknown>(request: APIRequestContext, url: string): Promise<T> {
  const r = await request.get(url);
  expect(r.ok(), `${url}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

async function entity(request: APIRequestContext, kind: string, name: string): Promise<Entity> {
  const list = await get<Entity[]>(request, `/api/memory/entities?kind=${kind}`);
  const found = list.find((e) => e.name === name);
  expect(found, `${kind} ${name}`).toBeTruthy();
  return found!;
}

async function texts(request: APIRequestContext, entityId: string, status = "active"): Promise<string[]> {
  const page = await get<{ items: Conclusion[] }>(request, `/api/memory/entities/${entityId}/conclusions?status=${status}`);
  return page.items.map((c) => c.text);
}

async function extractionIdle(request: APIRequestContext): Promise<boolean> {
  const jobs = await get<Job[]>(request, "/api/admin/jobs");
  return !jobs.some((j) => j.kind === "mem.extract" && (j.status === "queued" || j.status === "running"));
}

async function tool<T>(request: APIRequestContext, token: string, name: string, args: Record<string, unknown>): Promise<T> {
  const r = await request.post("/api/mcp", {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json, text/event-stream", "Content-Type": "application/json" },
    data: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } },
  });
  const result = (await r.json()).result;
  const text: string = result.content?.[0]?.text ?? "";
  if (result.isError) throw new Error(`${name}: ${text}`);
  const structured = result.structuredContent;
  return (structured ? (structured.result ?? structured) : JSON.parse(text)) as T;
}

test("memory: learn, forget, dream, ask, scope and MCP", async ({ page, browser }) => {
  test.setTimeout(240_000);
  await setupOrSignIn(page);
  const request = page.request;

  // 1. one provider for every AI job; each job's Test works in fake mode
  const provider = await post<{ id: string }>(request, "/api/admin/ai/providers", { name: "Memory provider", kind: "openai", api_key: "sk-e2e" });
  await page.goto("/admin/ai");
  const jobs = page.locator("section", { hasText: "Models per job" });
  for (const label of ["Embeddings", "Extraction", "Dreaming", "Answering"]) {
    const row = jobs.locator("form", { hasText: label });
    await row.getByLabel("Provider").selectOption(provider.id);
    await row.getByLabel("Model").fill(label === "Embeddings" ? "text-embedding-3-small" : "gpt-test");
    await row.getByRole("button", { name: "Save" }).click();
    await expect(row.getByRole("status")).toHaveText("Saved.");
    await row.getByRole("button", { name: "Test" }).click();
    await expect(row.getByRole("status")).toContainText("Works: fake/");
  }

  // 2. a comment on MEM-1 becomes a sourced conclusion about the MEM project
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Memory Team", description: "" });
  await post(request, "/api/projects", { key: "MEM", name: "Memory", description: "", team_ids: [team.id] });
  await post(request, "/api/projects/MEM/tasks", { title: "Go", type: "task" });
  const comment = await post<{ id: string }>(request, "/api/tasks/MEM-1/comments", { body_md: `${WEBHOOK_FACT}.` });
  const mem = await entity(request, "project", "MEM — Memory");
  await expect.poll(() => texts(request, mem.id), { timeout: 60_000 }).toContain(WEBHOOK_FACT);

  // 3. delete it in the UI; editing the comment does not bring it back
  await page.goto(`/memory/entity/${mem.id}`);
  const item = page.getByRole("listitem").filter({ hasText: WEBHOOK_FACT });
  await expect(item.getByRole("link", { name: "Comment on MEM-1" })).toHaveAttribute("href", "/projects/MEM/tasks/1");
  await item.getByRole("button", { name: "Delete" }).click();
  const ask = page.getByRole("alertdialog", { name: "Delete this conclusion?" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused(); // the safe choice first
  await ask.getByRole("button", { name: "Delete" }).click();
  await expect.poll(() => texts(request, mem.id, "deleted"), { timeout: 10_000 }).toContain(WEBHOOK_FACT);
  const patched = await request.patch(`/api/comments/${comment.id}`, {
    data: { body_md: `${WEBHOOK_FACT.toLowerCase()}!` },
    headers: WEB,
  });
  expect(patched.ok()).toBeTruthy();
  await expect.poll(() => extractionIdle(request), { timeout: 60_000 }).toBe(true);
  expect(await texts(request, mem.id)).not.toContain(WEBHOOK_FACT);
  expect(await texts(request, mem.id)).not.toContain(WEBHOOK_FACT.toLowerCase());
  await page.reload();
  await page.getByRole("tab", { name: "Deleted" }).click();
  await expect(page.getByText(WEBHOOK_FACT)).toBeVisible();

  // 4. two org facts about billing; dreaming induces a pattern with its premises and writes the org card
  await post(request, "/api/memory/products", { name: "Atlas", description: "Billing product", project_ids: [] });
  const spaces = await get<{ id: string; kind: string }[]>(request, "/api/kb/spaces");
  const orgSpace = spaces.find((s) => s.kind === "org")!;
  await post(request, `/api/kb/spaces/${orgSpace.id}/documents`, {
    title: "Billing",
    body_md: "Billing invoices go out monthly. Billing disputes are handled within five days.",
  });
  const org = await entity(request, "org", "Organization");
  // other specs may have taught the org things too: wait for these two
  await expect
    .poll(() => texts(request, org.id), { timeout: 60_000 })
    .toEqual(expect.arrayContaining(["Billing invoices go out monthly", "Billing disputes are handled within five days"]));
  await page.goto("/admin/ai");
  await page.getByRole("button", { name: "Dream now" }).click();
  await expect
    .poll(async () => (await get<{ status: string }[]>(request, "/api/admin/memory/dreams"))[0]?.status, { timeout: 60_000 })
    .toBe("done");
  await page.goto(`/memory/entity/${org.id}`);
  await expect(page.getByRole("region", { name: "Summary cards" })).toContainText("Billing invoices go out monthly");
  const induced = page.getByRole("listitem").filter({ hasText: "Pattern: billing" }).first();
  await expect(induced.getByText("induced · 60%")).toBeVisible();
  await induced.getByRole("button", { name: "Why?" }).click();
  await expect(induced.getByText("Billing invoices go out monthly")).toBeVisible();
  await expect(induced.getByText("Billing disputes are handled within five days")).toBeVisible();

  // 5. ask the memory about MEM: the answer cites a conclusion
  await post(request, "/api/tasks/MEM-1/comments", { body_md: `${SIGNED_FACT}.` });
  await expect.poll(() => texts(request, mem.id), { timeout: 60_000 }).toContain(SIGNED_FACT);
  await page.goto("/memory");
  await page.getByLabel("Question").fill("How are webhooks signed?");
  await page.getByLabel("Project (optional)").selectOption("MEM");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("list", { name: "Sources" })).toContainText(SIGNED_FACT);

  // 6. a member of another team: the org card, but nothing from MEM
  const invite = await post<{ invite_url: string }>(request, "/api/admin/users/invite", {
    email: OUTSIDER.email,
    name: OUTSIDER.name,
    role: "member",
  });
  const outsiderTeam = await post<{ id: string }>(request, "/api/teams", { name: "Memory Outsiders", description: "" });
  const outsider = await browser.newContext({ baseURL: new URL(page.url()).origin });
  await post(outsider.request, "/api/auth/accept-invite", { token: invite.invite_url.split("/invite/")[1], password: OUTSIDER.password });
  const me = await get<{ user: { id: string } }>(outsider.request, "/api/auth/me");
  const put = await request.put(`/api/teams/${outsiderTeam.id}/members`, { data: { user_ids: [me.user.id] }, headers: WEB });
  expect(put.ok()).toBeTruthy();
  const orgSeen = await get<{ cards: { summary_md: string }[] }>(outsider.request, `/api/memory/entities/${org.id}`);
  expect(orgSeen.cards.length).toBe(1);
  expect((await outsider.request.get(`/api/memory/entities/${mem.id}`)).status()).toBe(404);
  const answer = await post<{ cited: { text: string }[] }>(outsider.request, "/api/memory/ask", { question: "How are webhooks signed?" });
  expect(answer.cited.map((c) => c.text)).not.toContain(SIGNED_FACT);
  await outsider.close();

  // 7. MCP with a personal token: the same scoped results
  const token = await post<{ secret: string }>(request, "/api/tokens", { name: "Memory e2e", scopes: ["mcp"] });
  const found = await tool<{ results: { text: string }[] }>(request, token.secret, "search_memory", { query: "webhooks signed", project_key: "MEM" });
  expect(found.results.map((r) => r.text)).toContain(SIGNED_FACT);
  const asked = await tool<{ cited: { text: string }[] }>(request, token.secret, "ask_memory", { question: "How are webhooks signed?", project_key: "MEM" });
  expect(asked.cited.map((c) => c.text)).toContain(SIGNED_FACT);
});
