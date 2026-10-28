import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));

import ProjectPage from "@/app/(app)/projects/[key]/page";

describe("project page", () => {
  it("sends the project's own address to its board", async () => {
    await ProjectPage({ params: Promise.resolve({ key: "TST" }) });
    expect(redirect).toHaveBeenCalledWith("/projects/TST/board");
  });
});
