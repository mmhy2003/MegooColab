import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let params: Record<string, string> = {};
let pathname = "/";
vi.mock("next/navigation", () => ({
  useParams: () => params,
  usePathname: () => pathname,
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import QuestionPage from "@/app/(app)/questions/[id]/page";
import ProjectLayout from "@/app/(app)/projects/[key]/layout";
import TaskPage from "@/app/(app)/projects/[key]/tasks/[number]/page";
import TeamPage from "@/app/(app)/teams/[id]/page";
import { ChatView } from "@/components/chats/ChatView";
import { chat } from "@/components/chats/__tests__/fixtures";
import { useShownTrail } from "@/lib/trail";

const PROJECT = { id: "p1", key: "PAY", name: "Payments", status: "active", sprints_enabled: false };
const ME = { user: { id: "u1", name: "M", email: "m@x.io", role: "member" } };
const RECORDS = { decisions: [], test_runs: [], unverified_steps: [] };
const DEFAULTS: Record<string, [number, unknown]> = { "/api/auth/me": [200, ME] };
const TEAM = "3f9a2c4e-1b2d-4c3e-8f00-123456789abc";

function serve(routes: Record<string, [number, unknown] | "pending">) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const route = routes[url];
      if (route === "pending") return new Promise<Response>(() => {});
      const [status, body] = route ?? DEFAULTS[url] ?? (url.endsWith("/records") ? [200, RECORDS] : [200, []]);
      return new Response(JSON.stringify(body), { status });
    }),
  );
}

/** The trail the top bar shows, as text, and its crumbs' links. */
function Probe() {
  const trail = useShownTrail(pathname);
  return (
    <p data-testid="trail">
      {trail.crumbs.map((c, i) => (
        <span key={i} data-href={c.href ?? ""}>
          {i > 0 && " › "}
          {c.label ?? "…"}
        </span>
      ))}
    </p>
  );
}

function show(ui: React.ReactNode) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
      <Probe />
    </QueryClientProvider>,
  );
}

const trail = () => screen.getByTestId("trail");
const hrefOf = (label: string) =>
  [...trail().querySelectorAll("span")].find((s) => s.textContent?.replace(" › ", "") === label)?.getAttribute("data-href");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the top bar's trail", () => {
  it("a project's board", async () => {
    params = { key: "pay" };
    pathname = "/projects/pay/board";
    serve({ "/api/projects/pay": [200, PROJECT] });
    show(<ProjectLayout>board</ProjectLayout>);
    await waitFor(() => expect(trail()).toHaveTextContent("Projects › Payments › Board"));
    expect(hrefOf("Projects")).toBe("/projects");
    expect(hrefOf("Payments")).toBe("/projects/PAY/board");
  });

  it("a project's chats tab", async () => {
    params = { key: "pay" };
    pathname = "/projects/pay/chats";
    serve({ "/api/projects/pay": [200, PROJECT] });
    show(<ProjectLayout>chats</ProjectLayout>);
    await waitFor(() => expect(trail()).toHaveTextContent("Projects › Payments › Chats"));
  });

  it("a task page", async () => {
    params = { key: "pay", number: "12" };
    pathname = "/projects/pay/tasks/12";
    serve({
      "/api/projects/pay": [200, PROJECT],
      "/api/projects/PAY": [200, PROJECT],
      "/api/tasks/PAY-12": "pending", // the task names itself as soon as it shows, before it loads
    });
    show(
      <ProjectLayout>
        <TaskPage />
      </ProjectLayout>,
    );
    await waitFor(() => expect(trail()).toHaveTextContent("Projects › Payments › PAY-12"));
  });

  it("a chat", async () => {
    pathname = "/chats/c1";
    serve({ "/api/chats/c1": [200, chat({ title: "Fix the empty email crash" })] });
    show(<ChatView chatId="c1" />);
    await waitFor(() => expect(trail()).toHaveTextContent("Chats › Fix the empty email crash"));
    expect(hrefOf("Chats")).toBe("/chats");
  });

  it("a team", async () => {
    params = { id: TEAM };
    pathname = `/teams/${TEAM}`;
    serve({ [`/api/teams/${TEAM}`]: [200, { id: TEAM, name: "Platform", members: [], projects: [], agents: [] }] });
    show(<TeamPage />);
    await waitFor(() => expect(trail()).toHaveTextContent("Teams › Platform"));
    expect(hrefOf("Teams")).toBe("/teams");
  });

  it("a question", async () => {
    params = { id: "q1" };
    pathname = "/questions/q1";
    serve({
      "/api/questions/q1": [200, {
        id: "q1", ref: "Q-3", target: { key: "PAY", name: "Payments" }, title: "Which retry policy?", body: "Which retry policy?",
        context: "", status: "queued", answer_md: null, citations: [], answer_source: null, answered_by: { user: null, agent: null },
        answering: null, draft: null, reject_reason: null, redacted: false, attempts: 0, from_task: null,
        asked_by: { user: { id: "u1", name: "Ann" }, agent: null }, preference: null, kb_document_id: null,
        kb_document_readable: false, created_at: "2026-10-26T10:00:00Z", answered_at: null, can_answer: false,
        can_approve: false, can_withdraw: false,
      }],
    });
    show(<QuestionPage />);
    await waitFor(() => expect(trail()).toHaveTextContent("Questions › Q-3 Which retry policy?"));
    expect(hrefOf("Questions")).toBe("/questions");
  });

  it("a record that is not found", async () => {
    params = { key: "pay", number: "99" };
    pathname = "/projects/pay/tasks/99";
    serve({ "/api/projects/pay": [200, PROJECT], "/api/tasks/PAY-99": [404, { detail: "task_not_found" }] });
    show(
      <ProjectLayout>
        <TaskPage />
      </ProjectLayout>,
    );
    await waitFor(() => expect(trail()).toHaveTextContent(/^Page not found$/));
  });
});
