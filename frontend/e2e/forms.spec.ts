import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { tool } from "./helpers/mcp";

/**
 * End-to-end test of MC-172: a connect-only agent asks a form question; the person sees it, Send stays off until the
 * required name is filled, sends it, and the thread shows the form read-only with the values; the agent's
 * get_task/activity carries the data. Creates the Form Team team and the FRM project, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };

// the example form get_form_guide gives agents: one required "Release name", a date, a choice and "Tell the team"
const EXAMPLE = JSON.parse(readFileSync(join(process.cwd(), "..", "backend", "app", "a2ui", "example.json"), "utf8"));

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("forms: an agent's form question is filled in and answered", async ({ page }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Form Team", description: "" });
  const members = await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  expect(members.ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "FRM", name: "Forms demo", description: "", team_ids: [team.id] });
  const task = await post<{ key: string }>(request, "/api/projects/FRM/tasks", {
    title: "Plan the release",
    type: "task",
    assignee_user_id: me,
  });
  const token = await post<{ secret: string }>(request, "/api/tokens", { name: "Forms e2e", scopes: ["mcp"] });

  const guide = await tool<{ catalog: { components: Record<string, unknown> } }>(request, token.secret, "get_form_guide", {});
  expect(guide.catalog.components).toHaveProperty("TextField");

  // the workflow is connect-only (the task is a person's): the question waits for the person
  await tool(request, token.secret, "ask_human", { key: task.key, question: "A few release details", form: EXAMPLE });

  await page.goto("/projects/FRM/tasks/1");
  await expect(page.getByText("A few release details")).toBeVisible();
  const name = page.getByLabel("Release name");
  await expect(name).toBeVisible();
  const send = page.getByRole("button", { name: "Send answer" });
  await expect(send).toBeDisabled();

  await name.fill("v2.0");
  await expect(page.getByLabel("Tell the team")).toBeChecked();
  await expect(send).toBeEnabled();
  await send.click();

  await expect(page.getByText("answered with the form")).toBeVisible();
  await expect(name).toBeDisabled();
  await expect(name).toHaveValue("v2.0");

  const activity = await request.get(`/api/tasks/${task.key}/activity?limit=200`);
  expect(activity.ok()).toBeTruthy();
  const items = (await activity.json()) as { type: string; question: { answer_data: { name?: string } | null } | null }[];
  const asked = items.find((i) => i.type === "question");
  expect(asked?.question?.answer_data?.name).toBe("v2.0");
});
