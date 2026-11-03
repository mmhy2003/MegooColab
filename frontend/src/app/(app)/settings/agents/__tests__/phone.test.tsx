import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let search = "agent=a1";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

import AgentsPage from "@/app/(app)/settings/agents/page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(params: string) {
  search = params;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AgentsPage />
    </QueryClientProvider>,
  );
}

const hiddenOnPhones = (el: Element) => el.closest("[class~='max-md:hidden']") !== null;

describe("My agents on a phone", () => {
  it("on phones the header and tabs hide while an agent's details are open", () => {
    show("tab=agents&agent=a1");
    expect(hiddenOnPhones(screen.getByRole("heading", { level: 1, name: "My agents" }))).toBe(true);
    expect(hiddenOnPhones(screen.getByRole("tablist", { name: "My agents" }))).toBe(true);
  });

  it("and so while a machine's are", () => {
    show("tab=runner&machine=new");
    expect(hiddenOnPhones(screen.getByRole("tablist", { name: "My agents" }))).toBe(true);
  });

  it("the list keeps its header, without the intro on phones", () => {
    show("tab=agents");
    expect(hiddenOnPhones(screen.getByRole("heading", { level: 1, name: "My agents" }))).toBe(false);
    // its intro paragraph hides on a phone (the header's wrapper hides the p inside it)
    expect(screen.getByText(/Register the coding agents/).closest("[class~='max-md:[&_p]:hidden']")).not.toBeNull();
  });
});
