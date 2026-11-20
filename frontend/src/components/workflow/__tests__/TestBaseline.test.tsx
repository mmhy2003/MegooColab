import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TestBaseline } from "@/components/workflow/TestBaseline";
import type { TestRun } from "@/lib/workflow";

const run = (extra: Partial<TestRun>): TestRun => ({
  id: "t0",
  stage: "build",
  step: 1,
  command: "uv run pytest",
  passed: false,
  total: 2186,
  failed: 2,
  skipped: 0,
  failing: ["tests/test_a.py::test_one", "tests/test_b.py::test_two"],
  on_base: false,
  baseline: true,
  marks: null,
  known_only: false,
  author: "Bot",
  created_at: "2026-11-20T10:00:00Z",
  ...extra,
});

afterEach(cleanup);

describe("TestBaseline", () => {
  it("names the tests that already fail before step 1", () => {
    render(<TestBaseline run={run({})} />);
    const box = screen.getByRole("region", { name: "Test baseline" });
    expect(within(box).getByText("Test baseline (before step 1) · 2 already failing — uv run pytest")).toBeInTheDocument();
    expect(within(box).getByText("tests/test_a.py::test_one")).toBeInTheDocument();
    expect(within(box).getByText("tests/test_b.py::test_two")).toBeInTheDocument();
    expect(box.querySelector("details")).toBeNull();
  });

  it("shows a green baseline with its passed count", () => {
    render(<TestBaseline run={run({ passed: true, total: 2186, failed: 0, skipped: 2, failing: [] })} />);
    expect(screen.getByText("Test baseline (before step 1) · ✓ 2,184 passed — uv run pytest")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("says how many are listed when the baseline is incomplete, with the names behind a disclosure", () => {
    render(<TestBaseline run={run({ failed: 340 })} />);
    const box = screen.getByRole("region", { name: "Test baseline" });
    expect(within(box).getByText("Test baseline (before step 1) · 340 already failing, 2 listed — uv run pytest")).toBeInTheDocument();
    expect(within(box).getByText("Listed tests (2)")).toBeInTheDocument();
    expect(within(box).getByText("tests/test_a.py::test_one").closest("details")).not.toBeNull();
  });
});
