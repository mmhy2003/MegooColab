import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Link from "next/link";
import { afterEach, describe, expect, it } from "vitest";

import { SideListLayout } from "@/components/nav/SideListLayout";

afterEach(cleanup);

const list = (
  <ul>
    <li>
      <Link href="/kb/doc/d2">Beta</Link>
    </li>
  </ul>
);

describe("SideListLayout", () => {
  it("shows the list beside the content", () => {
    render(
      <SideListLayout sideLabel="Files" side={list}>
        <p>Alpha body</p>
      </SideListLayout>,
    );
    expect(within(screen.getByRole("complementary", { name: "Files" })).getByRole("link", { name: "Beta" })).toBeInTheDocument();
    expect(screen.getByText("Alpha body")).toBeInTheDocument();
  });

  it("opens the list as a panel from its button and closes it when a link is picked", async () => {
    render(
      <SideListLayout sideLabel="Files" side={list}>
        <p>Alpha body</p>
      </SideListLayout>,
    );
    expect(screen.queryByRole("dialog", { name: "Files" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    const panel = screen.getByRole("dialog", { name: "Files" });
    await userEvent.click(within(panel).getByRole("link", { name: "Beta" }));
    expect(screen.queryByRole("dialog", { name: "Files" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Files" })).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Files" })).toBeNull();
  });

  it("hides the list while hideSide", () => {
    render(
      <SideListLayout sideLabel="Files" side={list} hideSide>
        <p>Editing</p>
      </SideListLayout>,
    );
    expect(screen.queryByRole("complementary", { name: "Files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Files" })).toBeNull();
    expect(screen.getByText("Editing")).toBeInTheDocument();
  });
});
