import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowSettings } from "@/components/project/WorkflowSettings";
import type { Project } from "@/lib/types";

const project = {
  id: "p1",
  key: "PAY",
  status: "active",
  finishing_option: "pull_request",
  pr_review: "none",
  pr_reviewer_agent_id: null,
  commit_docs_to_repo: false,
  send_back_on_changes_requested: false,
} as Project;

function setup(canEdit: boolean, reply: Response = new Response("{}", { status: 200 }), shown: Project = project) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) =>
    String(url).endsWith("/agents")
      ? new Response(JSON.stringify([{ id: "a9", name: "review-bot", status: "online", can_use: true, owner: { id: "u1", name: "Ann" } }]), { status: 200 })
      : reply.clone(),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowSettings project={shown} canEdit={canEdit} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Workflow settings", () => {
  it("says a closed project is why they cannot change, not the person's role", () => {
    setup(false, undefined, { ...project, status: "archived" } as Project);
    expect(screen.getByText("Read-only while the project is closed.")).toBeInTheDocument();
    expect(screen.queryByText("Only managers can change these.")).toBeNull();
  });

  it("saves finishing option", async () => {
    const fetchMock = setup(true);
    fireEvent.change(screen.getByLabelText("Default finishing option"), { target: { value: "merge_local" } });
    fireEvent.change(screen.getByLabelText("Pull request review"), { target: { value: "human" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/projects/PAY");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({
      finishing_option: "merge_local",
      pr_review: "human",
      pr_reviewer_agent_id: null,
      commit_docs_to_repo: false,
      send_back_on_changes_requested: false,
    });
  });

  it("the send-back checkbox saves and explains itself", async () => {
    const fetchMock = setup(true);
    const box = screen.getByLabelText("Send the task back when changes are requested on its pull request");
    expect(screen.getByText(/A 'changes requested' review, or a comment starting with \/fix, sends the task back to its agent\./)).toHaveTextContent(
      "A 'changes requested' review, or a comment starting with /fix, sends the task back to its agent. The agent fixes the code and pushes to the same pull request. At most 3 rounds, then it asks you. On GitLab, use a /fix comment.",
    );
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toMatchObject({ send_back_on_changes_requested: true });
  });

  it("pull request review: each choice explains itself, and Agent asks who reviews", async () => {
    const fetchMock = setup(true);
    expect(screen.getByRole("option", { name: "None" })).toHaveValue("none");
    expect(screen.queryByLabelText("Reviewer")).toBeNull();
    fireEvent.change(screen.getByLabelText("Pull request review"), { target: { value: "human" } });
    expect(screen.getByText(/The task waits until a person merges the pull request/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Pull request review"), { target: { value: "agent" } });
    expect(screen.getByText(/An agent reviews the pull request on the host, and merges it when it approves; changes it asks for go back to the task's agent \(at most 3 rounds, then it asks you\)\./)).toBeInTheDocument();
    const reviewer = screen.getByLabelText("Reviewer");
    expect(reviewer).toHaveValue("");
    expect(within(reviewer).getByRole("option", { name: "The task's own agent (fresh session)" })).toBeInTheDocument();
    await screen.findByRole("option", { name: "review-bot" });
    fireEvent.change(reviewer, { target: { value: "a9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const patch = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "PATCH") as unknown as [string, RequestInit];
    expect(JSON.parse(patch[1].body as string)).toMatchObject({ pr_review: "agent", pr_reviewer_agent_id: "a9" });
  });

  it("shows the options with their labels and help text", () => {
    setup(true);
    expect(screen.getByRole("option", { name: "Push and open a pull request" })).toHaveValue("pull_request");
    expect(screen.getByRole("option", { name: "Merge locally" })).toHaveValue("merge_local");
    expect(screen.getByRole("option", { name: "Keep the branch" })).toHaveValue("keep_branch");
    expect(screen.getByText("The task moves to Done as soon as the agent finishes; nobody reviews the pull request first.")).toBeInTheDocument();
    expect(screen.getByText(/docs\/superpowers\/specs\/KEY-design\.md/)).toBeInTheDocument();
  });

  it("says what the chosen finishing option does, and follows the choice", () => {
    setup(true);
    expect(screen.getByText(/pushes the task's branch and opens a pull request/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Default finishing option"), { target: { value: "merge_local" } });
    expect(screen.getByText(/in your own checkout on the agent's machine/)).toBeInTheDocument();
    expect(screen.queryByText(/opens a pull request \(a merge request on GitLab\)/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Default finishing option"), { target: { value: "keep_branch" } });
    expect(screen.getByText(/leaves the finished work committed on its own branch/)).toBeInTheDocument();
  });

  it("is read-only text for people who cannot manage", () => {
    setup(false);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText("Push and open a pull request")).toBeInTheDocument();
    expect(screen.getByText(/pushes the task's branch and opens a pull request/)).toBeInTheDocument();
  });

  it("shows the server error", async () => {
    setup(true, new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("You don't have permission to do that."));
  });
});
