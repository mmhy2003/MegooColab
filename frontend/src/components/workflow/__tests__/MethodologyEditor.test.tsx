import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MethodologyEditor } from "@/components/workflow/MethodologyEditor";

const KEYS: [string, string][] = [
  ["brainstorm", "brainstorm"],
  ["design_revision", "design"],
  ["plan", "plan"],
  ["build_implement", "build"],
  ["build_step_review", "build"],
  ["build_step_fix", "build"],
  ["review_final", "review"],
  ["review_fix", "review"],
  ["finish", "done"],
];

function setup(opts: { put?: Response } = {}) {
  let plan = { version: 3, body_md: "Plan text v3" };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const res = opts.put ?? new Response(JSON.stringify({ version: 4 }), { status: 200 });
      if (res.ok) plan = { version: 4, body_md: JSON.parse(init.body as string).body_md };
      return res.clone();
    }
    if (url === "/api/methodology") {
      return new Response(
        JSON.stringify(
          KEYS.map(([key, stage]) => ({
            key,
            stage,
            version: key === "plan" ? plan.version : 1,
            body_md: key === "plan" ? plan.body_md : `${key} text`,
            updated_at: "2026-10-25T10:00:00Z",
            updated_by: "u1",
          })),
        ),
        { status: 200 },
      );
    }
    if (url === "/api/methodology/plan/versions") {
      const vs = [3, 2, 1].map((version) => ({ version, created_at: `2026-10-2${version}T10:00:00Z`, created_by: "u1" }));
      if (plan.version === 4) vs.unshift({ version: 4, created_at: "2026-10-26T10:00:00Z", created_by: "u1" });
      return new Response(JSON.stringify(vs), { status: 200 });
    }
    if (url === "/api/methodology/plan/versions/2") {
      return new Response(
        JSON.stringify({ version: 2, key: "plan", body_md: "Old **plan** text", created_at: "2026-10-22T10:00:00Z", created_by: "u1" }),
        { status: 200 },
      );
    }
    if (url === "/api/users") return new Response(JSON.stringify([{ id: "u1", name: "Ann Admin" }]), { status: 200 });
    return new Response("[]", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MethodologyEditor />
    </QueryClientProvider>,
  );
  return fetchMock;
}

const planCard = () => screen.getByRole("region", { name: "plan" });
const planBox = async () => within(await screen.findByRole("region", { name: "plan" })).findByRole("textbox");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MethodologyEditor", () => {
  it("shows the six stages in order with their keys and versions", async () => {
    setup();
    await screen.findByRole("region", { name: "plan" });
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Brainstorm", "Design", "Plan", "Build", "Review", "Done"]);
    expect(within(planCard()).getByText("v3")).toBeInTheDocument();
    expect(screen.getAllByRole("region")).toHaveLength(9);
  });

  it("save posts body and shows new version", async () => {
    const fetchMock = setup();
    const box = await planBox();
    expect(box).toHaveValue("Plan text v3");
    expect(within(planCard()).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "Plan text edited" } });
    fireEvent.click(within(planCard()).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved as v4")).toBeInTheDocument();
    const put = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "PUT")!;
    expect(put[0]).toBe("/api/methodology/plan");
    expect(JSON.parse((put[1] as RequestInit).body as string)).toEqual({ body_md: "Plan text edited" });
    await waitFor(() => expect(within(planCard()).getByText("v4")).toBeInTheDocument());
  });

  it("counts characters and blocks saving over 50,000", async () => {
    setup();
    fireEvent.change(await planBox(), { target: { value: "x".repeat(50_001) } });
    expect(within(planCard()).getByText("50,001 / 50,000")).toBeInTheDocument();
    expect(within(planCard()).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("keeps the text on a conflict and offers Load latest", async () => {
    setup({ put: new Response(JSON.stringify({ detail: "methodology_conflict" }), { status: 409 }) });
    const box = await planBox();
    fireEvent.change(box, { target: { value: "My edit" } });
    fireEvent.click(within(planCard()).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Someone else saved this text first/)).toBeInTheDocument();
    expect(box).toHaveValue("My edit");
    fireEvent.click(within(planCard()).getByRole("button", { name: "Load latest" }));
    await waitFor(() => expect(box).toHaveValue("Plan text v3"));
  });

  it("shows history", async () => {
    setup();
    await screen.findByRole("region", { name: "plan" });
    fireEvent.click(within(planCard()).getByRole("button", { name: "History" }));
    const v2 = await within(planCard()).findByRole("button", { name: /v2/ });
    expect(within(planCard()).getAllByText(/Ann Admin/).length).toBeGreaterThan(0);
    fireEvent.click(v2);
    expect(await within(planCard()).findByText("plan", { selector: "strong" })).toBeInTheDocument();
  });

  it("restores an old version into the editor without saving", async () => {
    const fetchMock = setup();
    await screen.findByRole("region", { name: "plan" });
    fireEvent.click(within(planCard()).getByRole("button", { name: "History" }));
    fireEvent.click(await within(planCard()).findByRole("button", { name: /v2/ }));
    fireEvent.click(await within(planCard()).findByRole("button", { name: "Restore as new version" }));
    expect(within(planCard()).getByRole("textbox")).toHaveValue("Old **plan** text");
    expect(within(planCard()).getByRole("button", { name: "Save" })).toBeEnabled();
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "PUT")).toBe(false);
  });

  it("warns before leaving with unsaved edits", async () => {
    setup();
    const box = await planBox();
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    fireEvent.change(box, { target: { value: "dirty" } });
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("attributes obra/superpowers", async () => {
    setup();
    const link = await screen.findByRole("link", { name: "obra/superpowers" });
    expect(link).toHaveAttribute("href", "https://github.com/obra/superpowers");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/Adapted from/)).toBeInTheDocument();
  });
});
