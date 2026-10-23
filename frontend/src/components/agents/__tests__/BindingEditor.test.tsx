import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BindingEditor } from "@/components/agents/BindingEditor";
import type { Agent, Project } from "@/lib/types";

const projects = [{ id: "p1", key: "PAY", name: "Payments" }] as unknown as Project[];
const agent = { id: "a1", name: "Ann's Codex", bindings: [] } as unknown as Agent;

function fill(path: string) {
  fireEvent.click(screen.getByRole("button", { name: /add project/i }));
  fireEvent.change(screen.getByLabelText("Project"), { target: { value: "PAY" } });
  fireEvent.change(screen.getByLabelText("Local path"), { target: { value: path } });
  fireEvent.click(screen.getByRole("button", { name: /save bindings/i }));
}

afterEach(() => vi.unstubAllGlobals());

describe("BindingEditor", () => {
  it("rejects a relative path without calling the server", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<BindingEditor agent={agent} projects={projects} onSaved={vi.fn()} />);
    fill("code/payments");
    expect(await screen.findByText(/full path/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the bindings payload for absolute paths (Windows and POSIX)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    render(<BindingEditor agent={agent} projects={projects} onSaved={onSaved} />);
    fill("C:\\code\\payments");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/agents/a1/bindings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ bindings: [{ project_ref: "PAY", local_path: "C:\\code\\payments" }] });
  });

  it("shows friendly copy for project_not_accessible", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "project_not_accessible" }), { status: 422 })),
    );
    render(<BindingEditor agent={agent} projects={projects} onSaved={vi.fn()} />);
    fill("/home/me/code/payments");
    expect(await screen.findByText(/don't have access to that project/i)).toBeInTheDocument();
  });
});
