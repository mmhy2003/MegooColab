import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/kb" }));

import { StartDraftDialog } from "@/components/kb/drafts/StartDraftDialog";

const AGENTS = [
  { id: "a1", name: "laptop-claude", online: true, runner_ok: true },
  { id: "a2", name: "home-bot", online: false, runner_ok: true },
  { id: "a3", name: "old-bot", online: true, runner_ok: false },
];
const TREE = { folders: [{ id: "f1", parent_id: null, name: "Runbooks" }], documents: [] };

function renderDialog({ agents = AGENTS, kind = "project" as "project" | "team", document = undefined as
  { id: string; title: string } | undefined } = {}) {
  const posted: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posted.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ id: "d9" }), { status: 201 });
    }
    const body = url.includes("/agents") ? agents : url.includes("/tree") ? TREE : { results: [] };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StartDraftDialog open onClose={() => {}} space={{ id: "s1", kind, name: "Payments" }} folderId="f1"
        document={document} />
    </QueryClientProvider>,
  );
  return posted;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("StartDraftDialog", () => {
  it("lists the usable agents, marks the offline ones and disables an old runner's", async () => {
    renderDialog();
    expect(await screen.findByRole("option", { name: "laptop-claude" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "home-bot (offline)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "old-bot (runner needs updating)" })).toBeDisabled();
  });

  it("says why there is no agent, by the kind of space", async () => {
    renderDialog({ agents: [] });
    expect(await screen.findByText("No agent can work on this project")).toBeInTheDocument();
    cleanup();
    renderDialog({ agents: [], kind: "team" });
    expect(await screen.findByText("You have no agents")).toBeInTheDocument();
  });

  it("posts the brief, the agent, the folder and the tasks to read, then opens the draft", async () => {
    const posted = renderDialog();
    await screen.findByRole("option", { name: "laptop-claude" });
    fireEvent.change(screen.getByLabelText("What should this document be?"), { target: { value: "A deploy runbook" } });
    fireEvent.change(screen.getByLabelText("Let it read"), { target: { value: "pay-12" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(screen.getByText("PAY-12")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start drafting" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/kb/drafts/d9"));
    expect(posted).toEqual([{
      space_id: "s1", folder_id: "f1", document_id: null, agent_id: "a1", brief: "A deploy runbook",
      sources: [{ kind: "task", key: "PAY-12" }],
    }]);
  });

  it("asks what to change for an existing document, without a place to save into", async () => {
    renderDialog({ document: { id: "doc1", title: "Runbook" } });
    expect(await screen.findByLabelText("What should the agent change?")).toBeInTheDocument();
    expect(screen.queryByLabelText("Save into")).not.toBeInTheDocument();
  });
});
