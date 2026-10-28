import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusSection } from "@/components/project/StatusSection";

import { project } from "./fixture";

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

function mockFetch(count: number) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) =>
    url.endsWith("/workflows-in-progress")
      ? new Response(JSON.stringify({ count }), { status: 200 })
      : new Response(JSON.stringify(project({ status: "finished" })), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const puts = (fetchMock: ReturnType<typeof mockFetch>) =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT").map(([, init]) => JSON.parse(String(init?.body)));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StatusSection", () => {
  it("marks the current status", () => {
    mockFetch(0);
    wrap(<StatusSection project={project()} canChange />);
    expect(screen.getByRole("button", { name: "Active" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Finished" })).toHaveAttribute("aria-pressed", "false");
  });

  it("asks before closing when workflows are in progress", async () => {
    const fetchMock = mockFetch(2);
    wrap(<StatusSection project={project()} canChange />);
    await userEvent.click(screen.getByRole("button", { name: "Finished" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Finish PAY?");
    expect(dialog).toHaveTextContent("2 workflows in progress will be paused.");
    expect(puts(fetchMock)).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    await waitFor(() => expect(puts(fetchMock)).toEqual([{ status: "finished" }]));
  });

  it("closes at once when nothing is in progress", async () => {
    const fetchMock = mockFetch(0);
    wrap(<StatusSection project={project()} canChange />);
    await userEvent.click(screen.getByRole("button", { name: "Archived" }));
    await waitFor(() => expect(puts(fetchMock)).toEqual([{ status: "archived" }]));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("only shows the status to people who may not change it", () => {
    mockFetch(0);
    wrap(<StatusSection project={project({ status: "finished" })} canChange={false} />);
    expect(screen.getByText("Finished")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says what closing does", () => {
    mockFetch(0);
    wrap(<StatusSection project={project()} canChange />);
    const help = screen.getByText(/read-only/);
    expect(help).toHaveTextContent(
      "Finished and archived projects are read-only, agents can't start work in them, and the dashboard no longer counts them.",
    );
    expect(help).toHaveTextContent("Archived projects also leave the Projects list and the projects you can ask, and their tasks leave search.");
  });
});
