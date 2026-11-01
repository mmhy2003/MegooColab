import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { backNameOf, pathTrail, useRecordTrail, useShownTrail, useTrail, type Crumb } from "@/lib/trail";

afterEach(cleanup);

function Shown({ pathname }: { pathname: string }) {
  const trail = useShownTrail(pathname);
  return <p data-testid="trail">{trail.crumbs.map((c) => c.label ?? "…").join(" › ")}</p>;
}

function Page({ crumbs }: { crumbs: Crumb[] }) {
  useTrail(crumbs);
  return null;
}

function Record({ crumbs }: { crumbs: Crumb[] }) {
  useRecordTrail(crumbs);
  return null;
}

describe("pathTrail", () => {
  it.each([
    ["/", [{ label: "Dashboard" }]],
    ["/kb/search", [{ label: "Knowledge Base", href: "/kb" }, { label: "Search" }]],
    ["/admin/users", [{ label: "Admin" }, { label: "Users" }]],
    ["/settings/tokens", [{ label: "Settings" }, { label: "Access tokens" }]],
    ["/projects/new", [{ label: "Projects", href: "/projects" }, { label: "New project" }]],
    ["/teams/3f9a2c4e-1b2d-4c3e-8f00-123456789abc", [{ label: "Teams", href: "/teams" }, { label: null }]],
    ["/nowhere/at-all", [{ label: "nowhere", href: "/nowhere" }, { label: "at-all" }]],
  ])("pathTrail(%s)", (path, want) => expect(pathTrail(path)).toEqual(want));
});

describe("the shown trail", () => {
  it("a page's trail replaces the path trail, and the path trail returns when it unmounts", () => {
    const { rerender } = render(
      <>
        <Page crumbs={[{ label: "Teams", href: "/teams" }, { label: "Platform" }]} />
        <Shown pathname="/teams/3f9a2c4e-1b2d-4c3e-8f00-123456789abc" />
      </>,
    );
    expect(screen.getByTestId("trail")).toHaveTextContent("Teams › Platform");
    rerender(<Shown pathname="/teams/3f9a2c4e-1b2d-4c3e-8f00-123456789abc" />);
    expect(screen.getByTestId("trail")).toHaveTextContent("Teams › …");
  });

  it("a record's trail shows over the page's and the page's returns when the record closes", () => {
    const board = [{ label: "Projects", href: "/projects" }, { label: "Payments", href: "/projects/PAY/board" }, { label: "Board" }];
    const task = [{ label: "Projects", href: "/projects" }, { label: "Payments", href: "/projects/PAY/board" }, { label: "PAY-12" }];
    const { rerender } = render(
      <>
        <Record crumbs={task} />
        <Page crumbs={board} />
        <Shown pathname="/projects/PAY/board" />
      </>,
    );
    expect(screen.getByTestId("trail")).toHaveTextContent("Projects › Payments › PAY-12");
    rerender(
      <>
        <Page crumbs={board} />
        <Shown pathname="/projects/PAY/board" />
      </>,
    );
    expect(screen.getByTestId("trail")).toHaveTextContent("Projects › Payments › Board");
  });
});

describe("backNameOf", () => {
  it("backNameOf prefers backName, then the last label", () => {
    expect(backNameOf({ crumbs: [{ label: "Knowledge Base" }, { label: "Search" }], backName: 'results for "retry"' })).toBe('results for "retry"');
    expect(backNameOf({ crumbs: [{ label: "Chats" }, { label: "Fix it" }] })).toBe("Fix it");
    expect(backNameOf({ crumbs: [{ label: "Teams" }, { label: null }] })).toBeNull();
    expect(backNameOf({ crumbs: [] })).toBeNull();
  });
});
