import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowSettings } from "@/components/project/WorkflowSettings";
import type { Project } from "@/lib/types";

const project = {
  id: "p1",
  key: "PAY",
  finishing_option: "pull_request",
  require_human_code_review: false,
  commit_docs_to_repo: false,
} as Project;

function setup(canEdit: boolean, reply: Response = new Response("{}", { status: 200 })) {
  const fetchMock = vi.fn(async () => reply.clone());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowSettings project={project} canEdit={canEdit} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Workflow settings", () => {
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
    expect(screen.getByRole("option", { name: "Push and open a PR/MR" })).toHaveValue("pull_request");
    expect(screen.getByRole("option", { name: "Merge locally" })).toHaveValue("merge_local");
    expect(screen.getByRole("option", { name: "Keep the branch" })).toHaveValue("keep_branch");
    expect(screen.getByText("Agents open a PR/MR and wait for a person to approve it before Done.")).toBeInTheDocument();
    expect(screen.getByText("Also commits the approved design and plan under docs/superpowers/ in the task branch.")).toBeInTheDocument();
  });

  it("is read-only text for people who cannot manage", () => {
    setup(false);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText("Push and open a PR/MR")).toBeInTheDocument();
  });

  it("shows the server error", async () => {
    setup(true, new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("You don't have permission to do that."));
  });
});
