import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FinishFailures } from "@/components/workflow/FinishFailures";
import { type FinishTests, finishTestsSummary, type TestRun } from "@/lib/workflow";

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
  baseline: false,
  marks: null,
  known_only: false,
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

  it("leaves the diagnosis out with showDiagnosis={false}, the summary and the tests stay", () => {
    const t = tests({ diagnosis: "D", delivered: false });
    render(<FinishFailures tests={t} startBranch="develop" showDiagnosis={false} />);
    expect(screen.queryByText("Diagnosis")).toBeNull();
    expect(screen.queryByText("D")).toBeNull();
    expect(screen.getByText(finishTestsSummary(t, "develop"))).toBeInTheDocument();
    expect(screen.getByText("e2e/a.spec.ts:1")).toBeInTheDocument();
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

describe("FinishFailures bug tasks", () => {
  const items = () => within(screen.getByRole("list", { name: "Failing tests" })).getAllByRole("listitem");

  it("offers Create bug task on base and flaky rows, not on new ones", () => {
    const spy = vi.fn();
    render(<FinishFailures tests={tests()} startBranch="develop" onCreateBug={spy} />);
    const [newRow, baseRow, flakyRow] = items();
    expect(within(newRow).queryByRole("button", { name: "Create bug task" })).toBeNull();
    expect(within(flakyRow).getByRole("button", { name: "Create bug task" })).toBeInTheDocument();
    fireEvent.click(within(baseRow).getByRole("button", { name: "Create bug task" }));
    expect(spy).toHaveBeenCalledWith("e2e/b.spec.ts:2");
  });

  it("shows no button without onCreateBug", () => {
    render(<FinishFailures tests={tests()} startBranch="develop" />);
    expect(screen.queryByRole("button", { name: "Create bug task" })).toBeNull();
  });

  it("links the open bug instead", () => {
    const t = tests();
    t.failures[1] = { ...t.failures[1], bug: { key: "PAY-131", title: "Failing test: e2e/b.spec.ts:2" } };
    render(<FinishFailures tests={t} startBranch="develop" onCreateBug={() => {}} />);
    const link = screen.getByRole("link", { name: "Bug: PAY-131" });
    expect(link).toHaveAttribute("href", "/projects/PAY/board?task=PAY-131");
    expect(link).toHaveAttribute("title", "Failing test: e2e/b.spec.ts:2");
    expect(screen.getAllByRole("button", { name: "Create bug task" })).toHaveLength(1);
  });

  it("says this task when the task is the bug", () => {
    const t = tests();
    t.failures[2] = { ...t.failures[2], bug: { key: "PAY-1", title: "x" } };
    render(<FinishFailures tests={t} startBranch="develop" taskKey="PAY-1" onCreateBug={() => {}} />);
    const flakyRow = items()[2];
    expect(within(flakyRow).getByText("Bug: this task")).toBeInTheDocument();
    expect(within(flakyRow).queryByRole("link")).toBeNull();
    expect(within(flakyRow).queryByRole("button")).toBeNull();
  });

  it("disables the button while busy", () => {
    render(<FinishFailures tests={tests()} startBranch="develop" onCreateBug={() => {}} busy />);
    const buttons = screen.getAllByRole("button", { name: "Create bug task" });
    expect(buttons).toHaveLength(2);
    for (const b of buttons) expect(b).toBeDisabled();
  });
});
