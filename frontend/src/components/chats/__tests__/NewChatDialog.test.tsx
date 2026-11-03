import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/chats" }));

import { NewChatDialog } from "@/components/chats/NewChatDialog";

const ME = { user: { id: "u1", name: "Owen", email: "o@x.io", role: "member" } };
const PROJECTS = [{ id: "p1", key: "PAY", name: "Payments" }, { id: "p2", key: "WEB", name: "Web" }];
const AGENTS = [{ id: "a1", name: "laptop-claude", program: "claude_code", owner: { id: "u1" }, status: "online", can_use: true }];

function renderDialog(projectKey?: string, refuse?: string) {
  const posted: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/images") {
      return new Response(JSON.stringify({ id: "img-1", filename: "a.png", size: 4, content_type: "image/png" }), { status: 201 });
    }
    if (init?.method === "POST" && refuse) return new Response(JSON.stringify({ detail: refuse }), { status: 409 });
    if (init?.method === "POST") {
      posted.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ id: "c9" }), { status: 201 });
    }
    const body = url.includes("/api/auth/me") ? ME : url.includes("/agents") ? AGENTS : PROJECTS;
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NewChatDialog open onClose={() => {}} projectKey={projectKey} />
    </QueryClientProvider>,
  );
  return posted;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("NewChatDialog", () => {
  it("its selects stay inside the dialog", () => {
    renderDialog();
    expect(screen.getByLabelText("Project")).toHaveClass("min-w-0");
    expect(screen.getByLabelText("Agent")).toHaveClass("min-w-0");
  });

  it("needs a message, and sends any free agent by default", async () => {
    const posted = renderDialog("PAY");
    const send = screen.getByRole("button", { name: "Start chat" });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Fix the empty email crash" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "laptop-claude" })).toBeInTheDocument());
    fireEvent.click(send);
    await waitFor(() => expect(posted).toEqual([{ project_key: "PAY", agent_id: null, message: "Fix the empty email crash", image_ids: [] }]));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chats/c9"));
  });

  it("locks the project on a project's tab, and lets you pick it on the Chats page", async () => {
    renderDialog("PAY");
    expect(screen.getByLabelText("Project")).toBeDisabled();
    cleanup();
    renderDialog();
    await waitFor(() => expect(screen.getByRole("option", { name: "WEB — Web" })).toBeInTheDocument());
    expect(screen.getByLabelText("Project")).not.toBeDisabled();
  });

  it("sends the images added to the first message", async () => {
    const posted = renderDialog("PAY");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Like this" } });
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["PNG"], "a.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Start chat" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start chat" }));
    await waitFor(() => expect(posted).toEqual([{ project_key: "PAY", agent_id: null, message: "Like this", image_ids: ["img-1"] }]));
  });

  it("says so when the agent can't be sent images", async () => {
    renderDialog("PAY", "images_not_supported");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Like this" } });
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["PNG"], "a.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Start chat" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start chat" }));
    expect(await screen.findByText("Update the runner on that agent's machine to send images, or send it without them."))
      .toBeInTheDocument();
  });
});
