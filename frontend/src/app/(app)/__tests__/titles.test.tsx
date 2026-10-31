import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let params: Record<string, string> = {};
let pathname = "/";
vi.mock("next/navigation", () => ({
  useParams: () => params,
  usePathname: () => pathname,
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import KbDocumentPage from "@/app/(app)/kb/doc/[docId]/page";
import ProjectLayout from "@/app/(app)/projects/[key]/layout";
import TaskPage from "@/app/(app)/projects/[key]/tasks/[number]/page";

const PROJECT = { id: "p1", key: "PAY", name: "Payments", status: "active", sprints_enabled: false };

const ME = { user: { id: "u1", name: "M", email: "m@x.io", role: "member" } };
const RECORDS = { decisions: [], test_runs: [], unverified_steps: [] };
const DEFAULTS: Record<string, [number, unknown]> = { "/api/auth/me": [200, ME] };

function serve(routes: Record<string, [number, unknown]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const [status, body] = routes[url] ?? DEFAULTS[url] ?? (url.endsWith("/records") ? [200, RECORDS] : [200, []]);
      return new Response(JSON.stringify(body), { status });
    }),
  );
}

function show(ui: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.title = "MegooColab";
});

describe("the browser tab's title", () => {
  it("names a project's tab", async () => {
    params = { key: "pay" };
    pathname = "/projects/pay/board";
    serve({ "/api/projects/pay": [200, PROJECT] });
    show(<ProjectLayout>board</ProjectLayout>);
    await waitFor(() => expect(document.title).toBe("PAY Board · MegooColab"));
  });

  it("says a task that is gone isn't found, over the project's title", async () => {
    params = { key: "pay", number: "99" };
    pathname = "/projects/pay/tasks/99";
    serve({ "/api/projects/pay": [200, PROJECT], "/api/tasks/PAY-99": [404, { detail: "task_not_found" }] });
    show(
      <ProjectLayout>
        <TaskPage />
      </ProjectLayout>,
    );
    await waitFor(() => expect(document.title).toBe("Page not found · MegooColab"));
  });

  it("names a Knowledge Base document once it loads", async () => {
    params = { docId: "d1" };
    pathname = "/kb/doc/d1";
    serve({ "/api/kb/documents/d1": [200, { id: "d1", title: "Release routine", space: { id: "s1", name: "Eng" }, body_md: "", can_write: false, latest_revision: 1, updated_by: { user: { name: "M" }, agent: null }, updated_at: "2026-10-30T10:00:00Z", folder_path: [] }] });
    show(<KbDocumentPage />);
    await waitFor(() => expect(document.title).toBe("Release routine · Knowledge Base · MegooColab"));
  });
});
