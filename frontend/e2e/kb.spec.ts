import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { tool } from "./helpers/mcp";

/**
 * End-to-end test of Plan 4, the Knowledge Base: AI settings, spaces and folders, editing with a stale-tab
 * conflict, history and diff, wiki links and backlinks, full-text and semantic search (fake embeddings, the
 * worker indexes in the background), space permissions, the MCP tools, and filing an approved design.
 * Needs a stack started with AI_FAKE=true (see README "Knowledge Base end-to-end test"). Project key KBX.
 */

const WEB = { "X-Megoo-Client": "web" };
const OUTSIDER = { name: "Olga Outside", email: "olga@acme.io", password: "olga-password-1" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

async function get<T = unknown>(request: APIRequestContext, url: string): Promise<T> {
  const r = await request.get(url);
  expect(r.ok(), `${url}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

type Space = { id: string; kind: string; name: string };
type Doc = { id: string; latest_revision: number; title: string };
type Hit = { document_id: string; title: string };

async function spaceNamed(request: APIRequestContext, name: string): Promise<Space> {
  const spaces = await get<Space[]>(request, "/api/kb/spaces");
  const space = spaces.find((s) => s.name === name);
  expect(space, `space ${name}`).toBeTruthy();
  return space!;
}

async function searchIds(request: APIRequestContext, q: string): Promise<string[]> {
  const body = await get<{ results: Hit[] }>(request, `/api/kb/search?q=${encodeURIComponent(q)}`);
  return body.results.map((r) => r.document_id);
}

async function openSpace(page: Page, name: string) {
  await page.goto("/kb");
  await page.getByRole("link", { name }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

test("knowledge base: edit, link, search, permissions, MCP and filing", async ({ page, browser }) => {
  await setupOrSignIn(page);
  const request = page.request;

  // 1. an embeddings provider; fake mode accepts it and the test call works
  await page.goto("/admin/ai");
  const providers = page.locator("section", { hasText: "Providers" });
  await providers.getByRole("button", { name: "Add provider" }).click();
  await providers.getByLabel("Name").fill("Local test provider");
  await providers.getByLabel("Kind").fill("openai");
  await providers.getByLabel("API key").fill("sk-e2e-not-real");
  await providers.getByRole("button", { name: "Save" }).click();
  await expect(providers.getByText("Key saved")).toBeVisible();
  await expect(page.getByText("sk-e2e-not-real")).toHaveCount(0);
  // the embeddings job's row (the extraction, dreaming and answering jobs have their own)
  await page.getByRole("tab", { name: "Models per job" }).click();
  const jobs = page.locator("section", { hasText: "Models per job" }).locator("form", { hasText: "Embeddings" });
  await jobs.getByLabel("Provider").selectOption({ label: "Local test provider" });
  await jobs.getByLabel("Model").fill("text-embedding-3-small");
  await jobs.getByRole("button", { name: "Save" }).click();
  await expect(jobs.getByRole("status")).toHaveText("Saved.");
  await jobs.getByRole("button", { name: "Test" }).click();
  await expect(jobs.getByRole("status")).toHaveText("Works: fake/embed-64");

  // 2. a folder and a document in the organization space, edited twice; the second edit from a stale tab
  await openSpace(page, "Organization");
  await page.getByRole("button", { name: "New folder" }).click();
  await page.getByLabel("Folder name").fill("Guides");
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("tree").getByRole("button", { name: "Guides", exact: true }).click();
  await expect(page).toHaveURL(/\?folder=/);
  await page.getByRole("button", { name: "New document" }).click();
  await page.getByLabel("Title").fill("Release process");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/kb\/doc\/[0-9a-f-]+\?edit=1/);
  const orgDocId = page.url().match(/\/kb\/doc\/([0-9a-f-]+)/)![1];
  await page.getByLabel("Body").fill("We ship on Tuesdays.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "Release process" })).toBeVisible();
  await expect(page.getByText("rev 2")).toBeVisible(); // rev 1 was the empty draft
  await expect(page.getByText("Guides/Release process")).toBeVisible();

  const stale = await page.context().newPage();
  await stale.goto(`/kb/doc/${orgDocId}?edit=1`);
  await expect(stale.getByLabel("Body")).toHaveValue("We ship on Tuesdays.");

  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").fill("We ship on Tuesdays and Thursdays.");
  await page.getByLabel("Summary of change (optional)").fill("twice a week");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("rev 3")).toBeVisible();

  await stale.getByLabel("Body").fill("We ship on Fridays.");
  await stale.getByRole("button", { name: "Save" }).click();
  await expect(stale.getByText("Someone saved a newer version")).toBeVisible();
  await expect(stale.getByLabel("Body")).toHaveValue("We ship on Fridays.");
  await stale.close();

  await page.getByRole("tab", { name: "history" }).click();
  await expect(page.getByText("twice a week")).toBeVisible();
  await page.getByRole("checkbox", { name: "rev 1" }).check();
  await page.getByRole("checkbox", { name: "rev 3" }).check();
  const changes = page.getByRole("list", { name: "Changes" });
  await expect(changes.getByRole("listitem", { name: "Added line 1" })).toContainText("We ship on Tuesdays and Thursdays.");

  // 3. a project with a task; a project-space document links to the task and to the org document
  const team = await post<{ id: string }>(request, "/api/teams", { name: "KB Team", description: "" });
  await post(request, "/api/projects", { key: "KBX", name: "Knowledge", description: "", team_ids: [team.id] });
  await post(request, "/api/projects/KBX/tasks", { title: "Document the release train", type: "task" });
  const projectSpace = await spaceNamed(request, "KBX — Knowledge");
  const linking = await post<Doc>(request, `/api/kb/spaces/${projectSpace.id}/documents`, {
    title: "Release checklist",
    body_md: `Before [[KBX-1]] ships, read [[doc:${orgDocId}|the release process]].`,
  });
  await page.goto("/projects/KBX/tasks/1");
  await expect(page.getByRole("heading", { name: "Referenced in Knowledge Base" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Release checklist" })).toBeVisible();
  await page.goto(`/kb/doc/${linking.id}`);
  await expect(page.getByRole("link", { name: "the release process" })).toHaveAttribute("href", `/kb/doc/${orgDocId}`);
  await expect(page.getByRole("link", { name: "KBX-1" })).toHaveAttribute("href", "/projects/KBX/tasks/1");
  await page.goto(`/kb/doc/${orgDocId}`);
  await expect(page.getByRole("region", { name: "Backlinks" }).getByRole("link", { name: "Release checklist" })).toBeVisible();

  // 4. full-text search finds both; a word only the vectors match is found once the worker has embedded it
  const webhooks = await post<Doc>(request, `/api/kb/spaces/${projectSpace.id}/documents`, {
    title: "Webhooks",
    body_md: "Delivery retries for webhooks with exponential backoff.",
  });
  expect(await searchIds(request, "release")).toEqual(expect.arrayContaining([orgDocId, linking.id]));
  await expect.poll(() => searchIds(request, "webhook"), { timeout: 30_000 }).toContain(webhooks.id);
  await page.goto("/kb/search?q=release");
  await expect(page.getByRole("link", { name: "Release process" })).toBeVisible();
  await expect(page.getByText(/Semantic search is off/)).toHaveCount(0);

  // 5. a member of another team sees the org document but nothing from the project or the KB Team space
  const invite = await post<{ invite_url: string }>(request, "/api/admin/users/invite", {
    email: OUTSIDER.email,
    name: OUTSIDER.name,
    role: "member",
  });
  const outsiderTeam = await post<{ id: string }>(request, "/api/teams", { name: "Outside Team", description: "" });
  const teamSpace = await spaceNamed(request, "KB Team");
  const secret = await post<Doc>(request, `/api/kb/spaces/${teamSpace.id}/documents`, {
    title: "Team release secrets",
    body_md: `Release notes for [[doc:${orgDocId}]] — internal.`,
  });
  const outsider = await browser.newContext({ baseURL: page.url().split("/kb")[0] });
  const token = invite.invite_url.split("/invite/")[1];
  await post(outsider.request, "/api/auth/accept-invite", { token, password: OUTSIDER.password });
  const me = await get<{ user: { id: string } }>(outsider.request, "/api/auth/me");
  const put = await request.put(`/api/teams/${outsiderTeam.id}/members`, { data: { user_ids: [me.user.id] }, headers: WEB });
  expect(put.ok()).toBeTruthy();
  const seen = await searchIds(outsider.request, "release");
  expect(seen).toContain(orgDocId);
  expect(seen).not.toContain(secret.id);
  expect(seen).not.toContain(linking.id);
  const back = await get<{ id: string }[]>(outsider.request, `/api/kb/documents/${orgDocId}/backlinks`);
  expect(back).toEqual([]);
  expect((await outsider.request.get(`/api/kb/documents/${secret.id}`)).status()).toBe(404);
  await outsider.close();

  // 6. MCP with a personal token: search, read, then write a document into a new folder path; it shows up live
  const created = await post<{ secret: string }>(request, "/api/tokens", { name: "KB e2e", scopes: ["mcp"] });
  const org = await spaceNamed(request, "Organization");
  await openSpace(page, "Organization");
  const found = await tool<{ results: Hit[] }>(request, created.secret, "kb_search", { query: "release" });
  expect(found.results.map((r) => r.document_id)).toContain(orgDocId);
  const read = await tool<{ body_md: string; revision: number }>(request, created.secret, "kb_read", { document_id: orgDocId });
  expect(read).toMatchObject({ body_md: "We ship on Tuesdays and Thursdays.", revision: 3 });
  const written = await tool<{ path: string; title: string }>(request, created.secret, "kb_write", {
    space_id: org.id,
    folder_path: "guides/api",
    title: "Webhooks",
    body_md: "Sign every webhook.",
  });
  expect(written).toMatchObject({ path: "guides/api", title: "Webhooks" });
  await expect(page.getByRole("tree").getByRole("button", { name: "guides", exact: true })).toBeVisible({ timeout: 10_000 });

  // 7. a connect-only design: approving it files it under Designs & Plans/<KEY>/Design
  const admin = await get<{ user: { id: string } }>(request, "/api/auth/me");
  const mine = await post<{ key: string }>(request, "/api/projects/KBX/tasks", {
    title: "Design the archive",
    type: "task",
    assignee_user_id: admin.user.id,
  });
  await tool(request, created.secret, "submit_design", { key: mine.key, markdown: "# Archive design\n\nKeep 90 days." });
  await post(request, `/api/tasks/${mine.key}/documents/design/1/decision`, { approve: true });
  const wf = await get<{ kb_documents: { kind: string; document_id: string }[] }>(request, `/api/tasks/${mine.key}/workflow`);
  const filed = wf.kb_documents.find((k) => k.kind === "design");
  expect(filed).toBeTruthy();
  const filedDoc = await get<{ path: string; title: string; body_md: string }>(request, `/api/kb/documents/${filed!.document_id}`);
  expect(filedDoc).toMatchObject({ path: `Designs & Plans/${mine.key}`, title: "Design" });
  expect(filedDoc.body_md).toContain("Keep 90 days.");
  await page.goto(`/projects/KBX/tasks/${mine.key.split("-")[1]}`);
  await expect(page.getByRole("link", { name: "View in Knowledge Base" })).toHaveAttribute("href", `/kb/doc/${filed!.document_id}`);
});
