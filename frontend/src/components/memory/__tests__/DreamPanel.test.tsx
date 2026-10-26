import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobModels } from "@/components/ai/JobModels";
import { DreamPanel } from "@/components/memory/DreamPanel";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const RUN = {
  id: "r1",
  trigger: "scheduled",
  status: "done",
  stats: { cards: 4, replaced: 2, deduced: 1, induced: 3 },
  error: null,
  started_at: "2026-10-26T03:00:00Z",
  finished_at: "2026-10-26T03:02:00Z",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("JobModels", () => {
  it("lists all four jobs with help", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/admin/ai/jobs"
          ? json(["embeddings", "extraction", "dreaming", "answering"].map((job) => ({ job, provider_id: null, model: "" })))
          : json([]),
      ),
    );
    wrap(<JobModels />);
    for (const label of ["Embeddings", "Extraction", "Dreaming", "Answering"]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/records short conclusions/)).toBeInTheDocument();
    expect(screen.getByText(/Nightly consolidation/)).toBeInTheDocument();
    expect(screen.getByText("Answers questions asked of the memory.")).toBeInTheDocument();
  });
});

describe("DreamPanel", () => {
  it("shows failed pairs, dropped items and the error", async () => {
    const failed = { ...RUN, status: "failed", stats: { pairs: 2, cards: 0, failed_pairs: 2, dropped: 3 }, error: "AiBadOutput: x" };
    vi.stubGlobal("fetch", vi.fn(async () => json([failed])));
    wrap(<DreamPanel />);
    expect(await screen.findByText("0 cards, 0 replaced, 0 deduced, 0 induced, 2 failed, 3 dropped")).toBeInTheDocument();
    expect(screen.getByText("AiBadOutput: x")).toBeInTheDocument();
  });

  it("shows runs and dream now", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "POST" ? json({ ...RUN, id: "r2", status: "running", trigger: "manual" }, 201) : json([RUN]),
    );
    vi.stubGlobal("fetch", fetchMock);
    wrap(<DreamPanel />);
    expect(await screen.findByText("4 cards, 2 replaced, 1 deduced, 3 induced")).toBeInTheDocument();
    expect(screen.getByText("scheduled")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dream now" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
    expect(fetchMock.mock.calls.find(([, i]) => i?.method === "POST")![0]).toBe("/api/admin/memory/dream");
  });

  it("shows already running", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        init?.method === "POST" ? json({ detail: "dream_running" }, 409) : json([]),
      ),
    );
    wrap(<DreamPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Dream now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A dream run is already in progress.");
  });
});
