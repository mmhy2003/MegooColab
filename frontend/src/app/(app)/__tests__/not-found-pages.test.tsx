import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let params: Record<string, string> = {};
vi.mock("next/navigation", () => ({
  useParams: () => params,
  usePathname: () => "/gone",
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import KbDocumentPage from "@/app/(app)/kb/doc/[docId]/page";
import KbSpacePage from "@/app/(app)/kb/[spaceId]/page";
import ProjectLayout from "@/app/(app)/projects/[key]/layout";
import TaskPage from "@/app/(app)/projects/[key]/tasks/[number]/page";

/** The server answers `status` with `detail` for `missing`, and an empty list for everything else. */
function serve(missing: string, status = 404, detail = "not_found") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === missing) return new Response(JSON.stringify({ detail }), { status });
      if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "M", email: "m@x.io", role: "member" } }));
      if (url.endsWith("/records")) return new Response(JSON.stringify({ decisions: [], test_runs: [], unverified_steps: [] }));
      return new Response("[]");
    }),
  );
}

function show(ui: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOT_FOUND = { level: 1, name: "This page doesn't exist" } as const;

describe("a page whose thing doesn't exist shows the not-found page", () => {
  it("a project", async () => {
    params = { key: "GONE" };
    serve("/api/projects/GONE", 404, "project_not_found");
    show(<ProjectLayout>board</ProjectLayout>);
    expect(await screen.findByRole("heading", NOT_FOUND)).toBeInTheDocument();
  });

  it("a task", async () => {
    params = { key: "pay", number: "99" };
    serve("/api/tasks/PAY-99", 404, "task_not_found");
    show(<TaskPage />);
    expect(await screen.findByRole("heading", NOT_FOUND)).toBeInTheDocument();
  });

  it("a Knowledge Base document", async () => {
    params = { docId: "d1" };
    serve("/api/kb/documents/d1", 404, "document_not_found");
    show(<KbDocumentPage />);
    expect(await screen.findByRole("heading", NOT_FOUND)).toBeInTheDocument();
  });

  it("a Knowledge Base space", async () => {
    params = { spaceId: "s1" };
    serve("/api/kb/spaces/s1/tree", 404, "space_not_found");
    show(<KbSpacePage />);
    expect(await screen.findByRole("heading", NOT_FOUND)).toBeInTheDocument();
  });
});

describe("any other failure keeps its own message", () => {
  it("a project the server couldn't load", async () => {
    params = { key: "PAY" };
    serve("/api/projects/PAY", 500, "boom");
    show(<ProjectLayout>board</ProjectLayout>);
    expect(await screen.findByText("Back to projects")).toBeInTheDocument();
    expect(screen.queryByRole("heading", NOT_FOUND)).not.toBeInTheDocument();
  });
});
