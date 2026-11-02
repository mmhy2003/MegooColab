import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectBindings } from "@/components/agents/ProjectBindings";
import type { Agent, Project } from "@/lib/types";

const PROJECTS = [
  { id: "p1", key: "PAY", name: "Payments" },
  { id: "p2", key: "WEB", name: "Website" },
] as unknown as Project[];
const PAY = { project_id: "p1", project_key: "PAY", local_path: "C:\\code\\payments" };
const agentWith = (bindings: Agent["bindings"]) => ({ id: "a1", name: "Ann's Codex", bindings }) as unknown as Agent;

// 14 bindings: P01..P12 under C:\code\p…, then Q13 and Q14 elsewhere
const MANY = Array.from({ length: 14 }, (_, i) => {
  const n = String(i + 1).padStart(2, "0");
  const key = i < 12 ? `P${n}` : `Q${n}`;
  return { project_id: `x${n}`, project_key: key, local_path: i < 12 ? `C:\\code\\p${n}` : `D:\\work\\q${n}` };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

function show(bindings: Agent["bindings"], fetchMock = vi.fn<Fetch>(async () => new Response("{}"))) {
  vi.stubGlobal("fetch", fetchMock);
  const onSaved = vi.fn(async () => undefined);
  render(<ProjectBindings agent={agentWith(bindings)} projects={PROJECTS} onSaved={onSaved} />);
  return { fetchMock, onSaved };
}

const putBody = (fetchMock: ReturnType<typeof vi.fn<Fetch>>) => {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
  return call && JSON.parse(String(call[1]?.body));
};

async function add(project: string, folder: string) {
  await userEvent.click(screen.getByRole("button", { name: "Add project" }));
  await userEvent.selectOptions(screen.getByLabelText("Project"), project);
  await userEvent.type(screen.getByLabelText("Folder"), folder);
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
}

describe("ProjectBindings", () => {
  it("adds a project in one row and saves at once", async () => {
    const { fetchMock, onSaved } = show([PAY]);
    await add("WEB", "/home/me/web");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe("/api/agents/a1/bindings");
    expect(putBody(fetchMock)).toEqual({
      bindings: [{ project_ref: "PAY", local_path: "C:\\code\\payments" }, { project_ref: "WEB", local_path: "/home/me/web" }],
    });
  });

  it("rejects a relative path without calling the server", async () => {
    const { fetchMock } = show([]);
    await add("PAY", "code/payments");
    expect(await screen.findByText(/full path/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows friendly copy for project_not_accessible", async () => {
    show([], vi.fn<Fetch>(async () => new Response(JSON.stringify({ detail: "project_not_accessible" }), { status: 422 })));
    await add("PAY", "/home/me/code/payments");
    expect(await screen.findByText(/don't have access to that project/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Folder")).toHaveValue("/home/me/code/payments");
  });

  it("only offers projects the agent isn't on", async () => {
    show([PAY]);
    await userEvent.click(screen.getByRole("button", { name: "Add project" }));
    const options = within(screen.getByLabelText("Project")).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options).toEqual(["", "WEB"]);
  });

  it("edits a folder in place", async () => {
    const { fetchMock } = show([PAY, { project_id: "p2", project_key: "WEB", local_path: "/srv/web" }]);
    await userEvent.click(screen.getByRole("button", { name: "Edit folder of PAY" }));
    const folder = screen.getByLabelText("Folder");
    await userEvent.clear(folder);
    await userEvent.type(folder, "D:\\pay");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(putBody(fetchMock)).toEqual({
        bindings: [{ project_ref: "PAY", local_path: "D:\\pay" }, { project_ref: "WEB", local_path: "/srv/web" }],
      }),
    );
  });

  it("asks before removing", async () => {
    const { fetchMock } = show([PAY, { project_id: "p2", project_key: "WEB", local_path: "/srv/web" }]);
    await userEvent.click(screen.getByRole("button", { name: "Remove PAY" }));
    let confirm = screen.getByRole("alertdialog", { name: "Remove PAY from Ann's Codex?" });
    expect(confirm).toHaveTextContent("The agent stops working on it.");
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Remove PAY" }));
    confirm = screen.getByRole("alertdialog", { name: "Remove PAY from Ann's Codex?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(putBody(fetchMock)).toEqual({ bindings: [{ project_ref: "WEB", local_path: "/srv/web" }] }));
  });

  it("shows 10 projects, then the rest on request", async () => {
    show(MANY);
    expect(screen.getByRole("heading", { name: "Projects (14)" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(10);
    await userEvent.click(screen.getByRole("button", { name: "Show 4 more" }));
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(14);
  });

  it("search shows every match", async () => {
    show(MANY);
    await userEvent.type(screen.getByLabelText("Search projects"), "c:\\code\\p");
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(12);
    expect(screen.queryByRole("button", { name: /^Show \d+ more$/ })).toBeNull();
  });

  it("disables the list while a save is in flight", async () => {
    let finish!: (r: Response) => void;
    show([PAY], vi.fn<Fetch>(() => new Promise<Response>((resolve) => (finish = resolve))));
    await add("WEB", "/home/me/web");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove PAY" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit folder of PAY" })).toBeDisabled();
    finish(new Response("{}"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove PAY" })).toBeEnabled());
  });

  it("says when the agent works on no project", () => {
    show([]);
    expect(screen.getByText("Not working on any project yet.")).toBeInTheDocument();
  });
});

describe("ProjectBindings after a save", () => {
  it("builds the next save on the last one even when the agent was not refetched", async () => {
    vi.stubGlobal("fetch", vi.fn<Fetch>(async () => new Response("{}")));
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn<Fetch>>;
    const projects = [...PROJECTS, { id: "p3", key: "API", name: "Public API" }] as unknown as Project[];
    // onSaved refetches nothing: the props keep the bindings from before the first save
    render(<ProjectBindings agent={agentWith([PAY])} projects={projects} onSaved={vi.fn(async () => undefined)} />);
    await add("WEB", "/srv/web");
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove WEB" })).toBeInTheDocument());
    await add("API", "/srv/api");
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "PUT")).toHaveLength(2));
    const last = fetchMock.mock.calls.filter(([, i]) => i?.method === "PUT").at(-1)!;
    expect(JSON.parse(String(last[1]?.body)).bindings.map((b: { project_ref: string }) => b.project_ref)).toEqual(["PAY", "WEB", "API"]);
  });

  it("shows a just-added project even past the first ten or outside a search", async () => {
    show(MANY);
    await userEvent.type(screen.getByLabelText("Search projects"), "q13");
    await add("PAY", "C:\\code\\payments");
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove PAY" })).toBeInTheDocument());
  });
});
