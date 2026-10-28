import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MethodologyEditor, type MethodologyStage } from "@/components/workflow/MethodologyEditor";
import { answer } from "@/test/answer";

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

/** The page keeps the open stage in the address; here it is plain state, starting on Plan. */
function Harness({ initial = "plan" }: { initial?: MethodologyStage }) {
  const [stage, setStage] = useState<MethodologyStage>(initial);
  return <MethodologyEditor stage={stage} onStage={setStage} />;
}

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
      <Harness />
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
  it("shows one tab per stage, each with its keys and versions", async () => {
    setup();
    await screen.findByRole("region", { name: "plan" });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Brainstorm", "Design", "Plan", "Build", "Review", "Done"]);
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    expect(within(planCard()).getByText("v3")).toBeInTheDocument();
    expect(screen.getAllByRole("region")).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: "Build" }));
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual([
      "build_implement", "build_step_review", "build_step_fix",
    ]);
  });

  it("marks a stage with unsaved edits and keeps them when switching tabs", async () => {
    setup();
    fireEvent.change(await planBox(), { target: { value: "Plan draft" } });
    expect(screen.getByRole("tab", { name: "Plan (unsaved changes)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Brainstorm" }));
    expect(screen.queryByRole("region", { name: "plan" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Plan (unsaved changes)" }));
    expect(await planBox()).toHaveValue("Plan draft");
    fireEvent.change(await planBox(), { target: { value: "Plan text v3" } }); // back to the saved text
    expect(screen.getByRole("tab", { name: "Plan" })).toBeInTheDocument();
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
    expect(JSON.parse((put[1] as RequestInit).body as string)).toEqual({ body_md: "Plan text edited", base_version: 3 });
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
    await answer("Discard");
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

  it("asks before restore or Load latest overwrites unsaved edits", async () => {
    setup({ put: new Response(JSON.stringify({ detail: "methodology_conflict" }), { status: 409 }) });
    const box = await planBox();
    fireEvent.click(within(planCard()).getByRole("button", { name: "History" }));
    fireEvent.click(await within(planCard()).findByRole("button", { name: /v2/ }));
    fireEvent.change(box, { target: { value: "My edit" } });
    fireEvent.click(await within(planCard()).findByRole("button", { name: "Restore as new version" }));
    expect(await screen.findByRole("alertdialog", { name: "Discard your changes?" })).toBeInTheDocument();
    await answer("Keep editing");
    expect(box).toHaveValue("My edit");
    fireEvent.click(within(planCard()).getByRole("button", { name: "Save" }));
    fireEvent.click(await within(planCard()).findByRole("button", { name: "Load latest" }));
    await answer("Keep editing");
    expect(box).toHaveValue("My edit");
    fireEvent.click(within(planCard()).getByRole("button", { name: "Load latest" }));
    await answer("Discard");
    await waitFor(() => expect(box).toHaveValue("Plan text v3"));
  });

  it("guards in-app link clicks while dirty", async () => {
    setup();
    const link = document.createElement("a");
    link.href = "/projects";
    document.body.appendChild(link);
    const followed: Event[] = []; // clicks that went through, as a link would follow them
    link.addEventListener("click", (e) => {
      if (!e.defaultPrevented) followed.push(e);
      e.preventDefault(); // jsdom: no real navigation
    });
    const clickLink = () => link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    clickLink();
    expect(followed).toHaveLength(1); // nothing unsaved: the link just works
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.change(await planBox(), { target: { value: "dirty" } });
    clickLink();
    expect(followed).toHaveLength(1); // stopped, and asked
    await answer("Keep editing");
    expect(followed).toHaveLength(1);
    clickLink();
    await answer("Discard");
    await waitFor(() => expect(followed).toHaveLength(2)); // the same link, followed after all
    link.remove();
  });

  it("keeps text typed while a save is in flight and blocks an empty body", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const fetchMock = setup();
    const inner = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") await gate;
      return inner(url, init);
    });
    const box = await planBox();
    fireEvent.change(box, { target: { value: "" } });
    expect(within(planCard()).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "sent" } });
    fireEvent.click(within(planCard()).getByRole("button", { name: "Save" }));
    fireEvent.change(box, { target: { value: "sent plus more" } });
    release();
    expect(await screen.findByText("Saved as v4")).toBeInTheDocument();
    expect(box).toHaveValue("sent plus more");
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

  it("sends the version a draft started from, even after another key's save refetched the list", async () => {
    const versions: Record<string, number> = Object.fromEntries(KEYS.map(([k]) => [k, 1]));
    versions.plan = 3;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const key = url.split("/").pop()!;
        const { base_version } = JSON.parse(init.body as string);
        if (base_version !== versions[key]) {
          return new Response(JSON.stringify({ detail: "methodology_conflict" }), { status: 409 });
        }
        versions[key] += 1;
        return new Response(JSON.stringify({ version: versions[key] }), { status: 200 });
      }
      if (url === "/api/methodology") {
        const list = KEYS.map(([key, stage]) => ({
          key, stage, version: versions[key], body_md: `${key} text v${versions[key]}`,
          updated_at: "2026-10-25T10:00:00Z", updated_by: "u1",
        }));
        return new Response(JSON.stringify(list), { status: 200 });
      }
      return new Response("[]", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
    const plan = await planBox();
    fireEvent.change(plan, { target: { value: "My plan edit" } }); // the draft of key A starts at v3
    versions.plan = 4; // meanwhile another admin saves plan
    fireEvent.click(screen.getByRole("tab", { name: "Brainstorm" }));
    const brainstorm = within(screen.getByRole("region", { name: "brainstorm" }));
    fireEvent.change(brainstorm.getByRole("textbox"), { target: { value: "Brainstorm edit" } });
    fireEvent.click(brainstorm.getByRole("button", { name: "Save" })); // key B: the list is refetched
    expect(await brainstorm.findByText("Saved as v2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Plan (unsaved changes)" }));
    await waitFor(() => expect(within(planCard()).getByText("v4")).toBeInTheDocument());

    fireEvent.click(within(planCard()).getByRole("button", { name: "Save" }));
    expect(await within(planCard()).findByText(/Someone else saved this text first/)).toBeInTheDocument();
    const planPuts = fetchMock.mock.calls.filter(
      (c) => c[0] === "/api/methodology/plan" && (c[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(JSON.parse((planPuts[0][1] as RequestInit).body as string)).toEqual({ body_md: "My plan edit", base_version: 3 });
    expect(plan).toHaveValue("My plan edit");
  });

  it("attributes obra/superpowers", async () => {
    setup();
    const link = await screen.findByRole("link", { name: "obra/superpowers" });
    expect(link).toHaveAttribute("href", "https://github.com/obra/superpowers");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/Adapted from/)).toBeInTheDocument();
  });
});
