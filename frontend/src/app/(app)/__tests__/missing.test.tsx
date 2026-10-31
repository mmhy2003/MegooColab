import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
const notFound = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url), notFound: () => notFound() }));

import MissingPage from "@/app/(app)/[...missing]/page";
import AdminPage from "@/app/(app)/admin/page";
import KbDocPage from "@/app/(app)/kb/doc/page";
import MemoryEntityPage from "@/app/(app)/memory/entity/page";
import TasksPage from "@/app/(app)/projects/[key]/tasks/page";
import SettingsPage from "@/app/(app)/settings/page";

describe("breadcrumb addresses with no page of their own", () => {
  it.each([
    ["admin", AdminPage, "/admin/users"],
    ["settings", SettingsPage, "/settings/profile"],
    ["kb/doc", KbDocPage, "/kb"],
    ["memory/entity", MemoryEntityPage, "/memory"],
  ])("/%s opens the nearest real page", (_path, Page, to) => {
    redirect.mockClear();
    Page();
    expect(redirect).toHaveBeenCalledWith(to);
  });

  it("a project's tasks address opens its board", async () => {
    redirect.mockClear();
    await TasksPage({ params: Promise.resolve({ key: "PAY" }) });
    expect(redirect).toHaveBeenCalledWith("/projects/PAY/board");
  });
});

describe("an address that matches no page", () => {
  it("shows the not-found page inside the app", () => {
    MissingPage();
    expect(notFound).toHaveBeenCalled();
  });
});
