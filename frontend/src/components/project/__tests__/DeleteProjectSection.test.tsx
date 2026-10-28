import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteProjectSection } from "@/components/project/DeleteProjectSection";
import type { User } from "@/lib/types";

import { project } from "./fixture";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const admin = { id: "u1", name: "Ada", email: "a@x.io", role: "admin" } as User;
const manager = { ...admin, role: "manager" } as User;

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("DeleteProjectSection", () => {
  it("is shown to admins only", () => {
    wrap(<DeleteProjectSection project={project()} user={manager} />);
    expect(screen.queryByRole("button", { name: "Delete project" })).toBeNull();
    cleanup();
    wrap(<DeleteProjectSection project={project()} user={admin} />);
    expect(screen.getByRole("button", { name: "Delete project" })).toBeInTheDocument();
  });

  it("enables Delete only when the key is typed exactly, then deletes and goes to the projects list", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<DeleteProjectSection project={project()} user={admin} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("what Memory learned only from it");
    const confirm = screen.getByRole("button", { name: "Delete PAY for good" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type PAY to confirm"), "pay");
    expect(confirm).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Type PAY to confirm"));
    await userEvent.type(screen.getByLabelText("Type PAY to confirm"), "PAY");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects"));
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/PAY", expect.objectContaining({ method: "DELETE" }));
  });
});
