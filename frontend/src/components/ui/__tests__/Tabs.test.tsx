import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/admin/settings",
  useSearchParams: () => new URLSearchParams(search),
}));

const TABS = [
  { id: "general", label: "General" },
  { id: "email", label: "Email" },
  { id: "search", label: "Search", mark: true },
] as const;
type Id = (typeof TABS)[number]["id"];

function Page() {
  const [tab, setTab] = useTabParam<Id>(TABS.map((t) => t.id));
  return (
    <>
      <Tabs label="Settings sections" tabs={TABS} value={tab} onChange={setTab} />
      {TABS.map((t) => (
        <TabPanel key={t.id} id={t.id} active={tab === t.id}>
          <p>{t.label} panel</p>
        </TabPanel>
      ))}
    </>
  );
}

const renderPage = () =>
  render(
    <Suspense>
      <Page />
    </Suspense>,
  );

beforeEach(() => {
  search = "";
  replace.mockReset();
});
afterEach(cleanup);

describe("Tabs", () => {
  it("opens the first tab when the address names none, or one that doesn't exist", () => {
    search = "tab=nope";
    renderPage();
    expect(screen.getByRole("tab", { name: "General" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "General" })).toHaveTextContent("General panel");
    expect(screen.queryByText("Email panel")).not.toBeVisible();
  });

  it("opens the tab the address names", () => {
    search = "tab=email";
    renderPage();
    expect(screen.getByRole("tab", { name: "Email" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Email" })).toBeVisible();
  });

  it("puts the chosen tab in the address without scrolling", () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Email" }));
    expect(replace).toHaveBeenCalledWith("/admin/settings?tab=email", { scroll: false });
  });

  it("moves between tabs with the arrow keys, Home and End", () => {
    renderPage();
    const general = screen.getByRole("tab", { name: "General" });
    expect(general).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Email" })).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(general, { key: "ArrowRight" });
    expect(replace).toHaveBeenLastCalledWith("/admin/settings?tab=email", { scroll: false });
    fireEvent.keyDown(general, { key: "ArrowLeft" });
    expect(replace).toHaveBeenLastCalledWith("/admin/settings?tab=search", { scroll: false });
    fireEvent.keyDown(general, { key: "End" });
    expect(replace).toHaveBeenLastCalledWith("/admin/settings?tab=search", { scroll: false });
    fireEvent.keyDown(general, { key: "Home" });
    expect(replace).toHaveBeenLastCalledWith("/admin/settings?tab=general", { scroll: false });
  });

  it("marks a tab with unsaved changes", () => {
    renderPage();
    expect(screen.getByRole("tab", { name: "Search (unsaved changes)" })).toBeInTheDocument();
  });
});
