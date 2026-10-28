import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusBanner } from "@/components/project/StatusBanner";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

import { project } from "./fixture";

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StatusBanner", () => {
  it("says nothing for an active project", () => {
    const { container } = wrap(<StatusBanner project={project()} canChange />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the finished banner with Reopen for those who may change it", () => {
    wrap(<StatusBanner project={project({ status: "finished" })} canChange />);
    expect(screen.getByRole("status")).toHaveTextContent("This project is finished. It is read-only.");
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });

  it("shows the archived banner, with no button for others", () => {
    wrap(<StatusBanner project={project({ status: "archived" })} canChange={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("This project is archived. It is read-only and hidden from lists.");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("Restore sets the project active", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      async () => new Response(JSON.stringify(project()), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    wrap(<StatusBanner project={project({ status: "archived" })} canChange />);
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects/PAY/status");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ status: "active" });
  });

  it("explains project_closed", () => {
    expect(errorMessage(new ApiError(409, "project_closed"))).toBe("This project is closed. Reopen it to make changes.");
  });
});
