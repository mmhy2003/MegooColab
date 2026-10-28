import { expect, test, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";

/**
 * End-to-end smoke test of Plan 1 against a fresh install:
 * setup → invite → team → project → task → live board updates across two browsers →
 * live comments → losing access when removed from the team.
 */

const MEMBER = { name: "Dev One", email: "dev@acme.io", password: "dev-password-1" };

function column(page: Page, name: string) {
  return page.getByRole("region", { name: `${name} column` });
}

test("foundation smoke", async ({ browser }) => {
  const adminCtx = await browser.newContext();
  const admin = await adminCtx.newPage();

  // 1. first-run setup (or sign in, when another spec has already set the organization up)
  await setupOrSignIn(admin);

  // 2. invite a member (no SMTP configured → copy the link)
  await admin.goto("/admin/users");
  await admin.getByRole("button", { name: "Invite" }).click();
  await admin.getByLabel("Email").fill(MEMBER.email);
  await admin.getByLabel("Name").fill(MEMBER.name);
  await admin.getByRole("button", { name: "Send invite" }).click();
  const inviteUrl = await admin.getByLabel("Invite link (valid 7 days)").inputValue();
  expect(inviteUrl).toContain("/invite/");
  await admin.getByRole("button", { name: "Done" }).click();

  // 3. team "Core" with both people
  await admin.goto("/teams");
  await admin.getByRole("button", { name: "New team" }).click();
  await admin.getByLabel("Name").fill("Core");
  await admin.getByRole("button", { name: "Create team" }).click();
  await expect(admin.getByRole("heading", { name: "Core" })).toBeVisible();
  await admin.getByRole("button", { name: "Edit members" }).click();
  await admin.getByRole("option", { name: new RegExp(ADMIN.name) }).click(); // tick them in the member list
  await admin.getByRole("option", { name: new RegExp(MEMBER.name) }).click(); // tick them in the member list
  await admin.getByRole("button", { name: "Save members" }).click();
  await expect(admin.getByText(MEMBER.name)).toBeVisible();

  // 4. project PAY owned by Core (continuous flow: sprints off)
  await admin.goto("/projects/new");
  await admin.getByLabel("Name").fill("Payments");
  await admin.getByLabel(/^Key/).fill("PAY");
  await admin.getByLabel("Core").check();
  await admin.getByRole("button", { name: "Create project" }).click();
  await expect(admin).toHaveURL(/\/projects\/PAY\/board/);

  // 4b. with sprints on (the default), work is created in the backlog
  await admin.goto("/projects/PAY/backlog");
  await admin.getByLabel("New backlog item").fill("Refund flow");
  await admin.getByLabel("New backlog item").press("Enter");
  await expect(admin.getByRole("region", { name: "Backlog" }).getByText("Refund flow")).toBeVisible();

  const patched = await admin.request.patch("/api/projects/PAY", {
    data: { sprints_enabled: false },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(patched.ok()).toBeTruthy();
  await admin.goto("/projects/PAY/board");

  // 5. task via quick-create
  await admin.getByLabel("New task in To Do").fill("Sync orders");
  await admin.getByLabel("New task in To Do").press("Enter");
  await expect(column(admin, "To Do").getByText("Sync orders")).toBeVisible();

  // 6. member accepts the invite and opens the board
  const memberCtx = await browser.newContext();
  const member = await memberCtx.newPage();
  await member.goto(inviteUrl);
  await member.getByLabel("New password", { exact: true }).fill(MEMBER.password);
  await member.getByLabel("Confirm new password").fill(MEMBER.password);
  await member.getByRole("button", { name: "Join" }).click();
  await expect(member).toHaveURL(/\/projects$/);
  await member.goto("/projects/PAY/board");
  await expect(column(member, "To Do").getByText("Sync orders")).toBeVisible();

  // 7. admin drags PAY-2 to In Progress; the member sees it move within 2 s
  const card = column(admin, "To Do").getByRole("button", { name: /PAY-2 Sync orders/ });
  const target = column(admin, "In Progress");
  const from = (await card.boundingBox())!;
  const to = (await target.boundingBox())!;
  await admin.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await admin.mouse.down();
  await admin.mouse.move(from.x + from.width / 2 + 20, from.y + from.height / 2, { steps: 5 });
  await admin.mouse.move(to.x + to.width / 2, to.y + 120, { steps: 15 });
  await admin.mouse.up();
  await expect(column(admin, "In Progress").getByText("Sync orders")).toBeVisible();
  await expect(column(member, "In Progress").getByText("Sync orders")).toBeVisible({ timeout: 2_000 });

  // 8. member comments; the admin's open task shows it live
  await admin.goto("/projects/PAY/board?task=PAY-2");
  await expect(admin.getByRole("dialog", { name: "PAY-2" })).toBeVisible();
  await member.goto("/projects/PAY/board?task=PAY-2");
  await member.getByLabel("Add a comment").fill("On it — **ERP** creds received.");
  await member.getByRole("button", { name: "Comment" }).click();
  await expect(admin.getByRole("dialog", { name: "PAY-2" }).getByText("creds received.")).toBeVisible({ timeout: 2_000 });

  // 9. removing the member from Core takes PAY away from them
  const team = (await (await admin.request.get("/api/teams")).json()).find((t: { name: string }) => t.name === "Core");
  const adminId = (await (await admin.request.get("/api/auth/me")).json()).user.id;
  const removed = await admin.request.put(`/api/teams/${team.id}/members`, {
    data: { user_ids: [adminId] },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(removed.ok()).toBeTruthy();
  await member.goto("/projects/PAY/board");
  await expect(member.getByText("Project not found.")).toBeVisible();

  await adminCtx.close();
  await memberCtx.close();
});
