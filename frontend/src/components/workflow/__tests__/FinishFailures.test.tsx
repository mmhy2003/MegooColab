import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FinishFailures } from "@/components/workflow/FinishFailures";
import type { FinishTests, TestRun } from "@/lib/workflow";

const tests = (extra: Partial<FinishTests> = {}): FinishTests => ({
  failures: [
    { name: "e2e/a.spec.ts:1", kind: "new" },
    { name: "e2e/b.spec.ts:2", kind: "base" },
    { name: "e2e/c.spec.ts:3", kind: "flaky" },
  ],
  failing_total: 8,
  diagnosis: null,
  delivered: true,
  settled: null,
  accepted_by: null,
  ...extra,
});

const run = (extra: Partial<TestRun>): TestRun => ({
  id: "t1",
  stage: "done",
  step: null,
  command: "npm test",
  passed: false,
  total: null,
  failed: 1,
  skipped: null,
  failing: ["e2e/a.spec.ts:1"],
  on_base: false,
  author: "Bot",
  created_at: "2026-11-20T10:00:00Z",
  ...extra,
});

afterEach(cleanup);

describe("FinishFailures", () => {
  it("lists the failing tests with their kinds", () => {
    render(<FinishFailures tests={tests()} startBranch="develop" />);
    expect(screen.getByText("Tests failed at finish: 8 failing (1 new, 1 also fails on develop, 1 flaky, 5 not listed)")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Failing tests" })).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "e2e/a.spec.ts:1new",
      "e2e/b.spec.ts:2also fails on develop",
      "e2e/c.spec.ts:3flaky",
      "and 5 more",
    ]);
    expect(screen.queryByText("Diagnosis")).toBeNull();
    expect(screen.queryByText(/Test runs at finish/)).toBeNull();
  });

  it("shows the diagnosis as plain text", () => {
    render(<FinishFailures tests={tests({ diagnosis: "<b>x</b>" })} startBranch="develop" />);
    expect(screen.getByText("Diagnosis")).toBeInTheDocument();
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
    expect(document.body.querySelector("b")).toBeNull();
  });

  it("lists the test runs at finish", () => {
    render(
      <FinishFailures
        tests={tests()}
        startBranch="develop"
        runs={[run({}), run({ id: "t2", on_base: true })]}
      />,
    );
    expect(screen.getByText("Test runs at finish (2)")).toBeInTheDocument();
    expect(screen.getByText("✗ 1 failed: e2e/a.spec.ts:1 — npm test")).toBeInTheDocument();
    expect(screen.getByText("✗ 1 failed: e2e/a.spec.ts:1 — npm test (on the start commit)")).toBeInTheDocument();
  });

  it("says how the finish settled", () => {
    render(
      <FinishFailures
        tests={tests({ failures: [{ name: "b", kind: "base" }, { name: "c", kind: "flaky" }], failing_total: null, settled: "known" })}
        startBranch="develop"
      />,
    );
    expect(screen.getByText("Finished with 2 known failing tests: 1 also fails on develop, 1 flaky")).toBeInTheDocument();
  });
});
