import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowSettings } from "@/components/project/WorkflowSettings";
import type { Project } from "@/lib/types";

const project = {
  id: "p1",
  key: "PAY",
  status: "active",
  finishing_option: "pull_request",
  require_human_code_review: false,
  commit_docs_to_repo: false,
} as Project;

function setup(canEdit: boolean, reply: Response = new Response("{}", { status: 200 }), shown: Project = project) {
  const fetchMock = vi.fn(async () => reply.clone());
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
    fireEvent.click(screen.getByLabelText("Require human code review before Done"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/projects/PAY");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({
      finishing_option: "merge_local",
      require_human_code_review: true,
      commit_docs_to_repo: false,
    });
  });

  it("shows the options with their labels and help text", () => {
    setup(true);
    expect(screen.getByRole("option", { name: "Push and open a pull request" })).toHaveValue("pull_request");
    expect(screen.getByRole("option", { name: "Merge locally" })).toHaveValue("merge_local");
    expect(screen.getByRole("option", { name: "Keep the branch" })).toHaveValue("keep_branch");
    expect(screen.getByText(/the work always ends as a pull request, whatever the finishing option says/)).toBeInTheDocument();
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
