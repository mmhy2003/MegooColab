import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EscalationActions } from "@/components/workflow/EscalationActions";
import { buttonClass } from "@/components/ui/Button";
import type { Workflow } from "@/lib/types";
import type { FinishTests } from "@/lib/workflow";

const finishTests = (extra: Partial<FinishTests> = {}): FinishTests => ({
  failures: [{ name: "greeting.test:1", kind: "new" }],
  failing_total: null,
  diagnosis: "The greeting test expects a farewell.",
  delivered: true,
  settled: null,
  accepted_by: null,
  ...extra,
});

function wf(extra: Partial<Workflow> = {}): Workflow {
  return {
    stage: "done",
    status: "waiting_human",
    needs: "escalation",
    escalation_reason: "finish_tests_failed",
    can_act: true,
    start_branch: "develop",
    finish_tests: finishTests(),
    ...extra,
  } as Workflow;
}

afterEach(cleanup);

describe("EscalationActions", () => {
  it("shows the failing tests at finish with Finish anyway", () => {
    render(<EscalationActions wf={wf()} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getByText("Tests failed at finish: 1 failing (1 new)")).toBeInTheDocument();
    expect(screen.getByText("greeting.test:1")).toBeInTheDocument();
    expect(screen.getByText("The greeting test expects a farewell.")).toBeInTheDocument();
    expect(screen.queryByText("Tests failed at finish.")).toBeNull();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Retry", "Finish anyway", "Pause"]);
    expect(screen.getByText("Finish anyway records that you accepted these tests and finishes the task.")).toBeInTheDocument();
  });

  it("says the agent delivers the work when it has not yet", () => {
    render(<EscalationActions wf={wf({ finish_tests: finishTests({ delivered: false }) })} canDecide busy={false} onDecide={() => {}} />);
    expect(
      screen.getByText("Finish anyway records that you accepted these tests; the agent then delivers the work and lists them in the pull request."),
    ).toBeInTheDocument();
  });

  it("Finish anyway accepts", () => {
    const onDecide = vi.fn();
    render(<EscalationActions wf={wf()} canDecide busy={false} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Finish anyway" }));
    expect(onDecide).toHaveBeenCalledWith("accept");
  });

  it("gives no hint to those who cannot decide", () => {
    render(<EscalationActions wf={wf()} canDecide={false} busy={false} onDecide={() => {}} />);
    expect(screen.queryByText(/Finish anyway records/)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps Accept for other reasons", () => {
    render(<EscalationActions wf={wf({ stage: "build", escalation_reason: "review_rounds_exhausted", finish_tests: null })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getByText("The step still had review findings after 3 review rounds.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.queryByText(/Finish anyway records/)).toBeNull();
  });

  it("shows the reason when there is no failure report", () => {
    render(<EscalationActions wf={wf({ finish_tests: null })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getByText("Tests failed at finish.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish anyway" })).toBeInTheDocument();
  });
  it("offers a fix round first while nothing was delivered", () => {
    render(<EscalationActions wf={wf({ finish_tests: finishTests({ delivered: false }), finish_fix_rounds: 0, finish_fix_max: 2 })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Fix round", "Retry", "Finish anyway", "Pause"]);
    expect(
      screen.getByText("Fix round: the agent fixes these tests in a fresh run, a reviewer checks the fix, then the finish runs again. Round 1 of 2."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fix round" }).className).toContain(buttonClass("primary"));
    expect(screen.getByRole("button", { name: "Retry" }).className).toContain(buttonClass("ghost"));
  });

  it("says the second round is the last", () => {
    render(<EscalationActions wf={wf({ finish_tests: finishTests({ delivered: false }), finish_fix_rounds: 1, finish_fix_max: 2 })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getByText(/Round 2 of 2\.$/)).toBeInTheDocument();
  });

  it("says both fix rounds are used and makes Retry the main button again", () => {
    render(<EscalationActions wf={wf({ finish_tests: finishTests({ delivered: false }), finish_fix_rounds: 2, finish_fix_max: 2 })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Retry", "Finish anyway", "Pause"]);
    expect(screen.getByText("Both fix rounds are used.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" }).className).toContain(buttonClass("primary"));
  });

  it("offers no fix round once the finish delivered", () => {
    render(<EscalationActions wf={wf({ finish_fix_rounds: 0, finish_fix_max: 2 })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Retry", "Finish anyway", "Pause"]);
    expect(screen.queryByText(/Fix round:/)).toBeNull();
    expect(screen.queryByText("Both fix rounds are used.")).toBeNull();
  });

  it("Fix round starts a fix round", () => {
    const onDecide = vi.fn();
    render(<EscalationActions wf={wf({ finish_tests: finishTests({ delivered: false }), finish_fix_rounds: 0, finish_fix_max: 2 })} canDecide busy={false} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Fix round" }));
    expect(onDecide).toHaveBeenCalledWith("fix");
  });

  it("explains a review of the fix that still had findings", () => {
    render(<EscalationActions wf={wf({ stage: "review", escalation_reason: "finish_fix_not_clean" })} canDecide busy={false} onDecide={() => {}} />);
    expect(screen.getByText("The review of the fix round still had findings.")).toBeInTheDocument();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Retry", "Accept", "Pause"]);
  });
});
