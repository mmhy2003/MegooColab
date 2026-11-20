import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StepTestRun } from "@/components/workflow/StepTestRun";
import { testRunText, type TestRun } from "@/lib/workflow";

const run = (extra: Partial<TestRun>): TestRun => ({
  id: "t1",
  stage: "build",
  step: 2,
  command: "uv run pytest",
  passed: false,
  total: 10,
  failed: 1,
  skipped: 0,
  failing: ["test_x"],
  on_base: false,
  baseline: false,
  marks: null,
  known_only: false,
  author: "Bot",
  created_at: "2026-11-20T10:00:00Z",
  ...extra,
});

afterEach(cleanup);

describe("StepTestRun", () => {
  it("shows today's line when the run has no marks", () => {
    const r = run({});
    render(<StepTestRun run={r} />);
    const line = screen.getByText(testRunText(r));
    expect(line).toHaveClass("text-pink");
  });

  it("says there are no new failures when every failing test is in the baseline", () => {
    render(<StepTestRun run={run({ failed: 2, failing: ["test_a", "test_b"], marks: ["baseline", "baseline"], known_only: true })} />);
    const line = screen.getByText("No new failures: 2 failed, both also fail in the baseline — uv run pytest");
    expect(line).toHaveClass("text-muted-foreground");
  });

  it("marks the new failures and the baseline ones", () => {
    render(<StepTestRun run={run({ failed: 3, failing: ["test_a", "test_b", "test_c"], marks: ["baseline", "new", "baseline"] })} />);
    expect(screen.getByText("✗ 3 failed, 1 new — uv run pytest")).toHaveClass("text-pink");
    expect(screen.getByText("new", { exact: true })).toHaveClass("text-pink");
    expect(screen.getAllByText("also fails in the baseline", { exact: true })).toHaveLength(2);
    expect(screen.getByText("new", { exact: true }).closest("li")).toHaveTextContent("test_b · new");
  });

  it("tags a failure the incomplete baseline doesn't list", () => {
    render(<StepTestRun run={run({ failed: 2, failing: ["test_a", "test_b"], marks: ["baseline", "unlisted"] })} />);
    expect(screen.getByText("✗ 2 failed, 1 not in the baseline's list — uv run pytest")).toBeInTheDocument();
    expect(screen.getByText("not in the baseline's list", { exact: true })).toHaveClass("text-muted-foreground");
  });

  it("says how many failures are not named", () => {
    const names = Array.from({ length: 20 }, (_, i) => `test_${i}`);
    render(<StepTestRun run={run({ failed: 25, failing: names, marks: names.map(() => "baseline" as const) })} />);
    expect(screen.getByText("✗ 25 failed, none new — uv run pytest")).toBeInTheDocument();
    expect(screen.getByText("and 5 more")).toBeInTheDocument();
  });
});
