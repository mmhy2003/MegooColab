import type { Locator } from "@playwright/test";

/** Assigns a task from its drawer or page: open the searchable assignee list, type, pick. */
export async function pickAssignee(scope: Locator, name: string): Promise<void> {
  await scope.getByRole("combobox", { name: "Assignee" }).click();
  // the list opens over the page, outside the drawer's own box
  const list = scope.page().getByRole("listbox");
  await scope.page().getByPlaceholder("Search people and agents").fill(name);
  await list.getByRole("option", { name, exact: true }).click();
}
