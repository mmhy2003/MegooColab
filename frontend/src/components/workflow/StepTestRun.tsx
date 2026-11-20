import { MARK_LABEL, testRunText, type TestRun } from "@/lib/workflow";

/** A step's latest test run on the plan; against a test baseline, each failing test says whether it is new (MC-99). */
export function StepTestRun({ run }: { run: TestRun }) {
  const marks = run.marks;
  if (marks == null) {
    return <p className={`text-xs ${run.passed ? "text-muted-foreground" : "text-pink"}`}>{testRunText(run)}</p>;
  }
  const n = run.failed ?? run.failing.length;
  if (run.known_only) {
    const all = n === 1 ? "it also fails" : n === 2 ? "both also fail" : "all also fail";
    return (
      <p className="text-xs text-muted-foreground">
        No new failures: {n} failed, {all} in the baseline — {run.command}
      </p>
    );
  }
  const fresh = marks.filter((m) => m === "new").length;
  const unlisted = marks.filter((m) => m === "unlisted").length;
  const parts = [...(fresh ? [`${fresh} new`] : []), ...(unlisted ? [`${unlisted} not in the baseline's list`] : [])];
  return (
    <>
      <p className="text-xs text-pink">
        ✗ {n} failed, {parts.length ? parts.join(", ") : "none new"} — {run.command}
      </p>
      <ul className="ml-3 text-xs">
        {run.failing.map((name, i) => {
          const mark = marks[i];
          return (
            <li key={name}>
              {name}
              {mark && (
                <>
                  {" · "}
                  <span className={mark === "new" ? "text-pink" : "text-muted-foreground"}>{MARK_LABEL[mark]}</span>
                </>
              )}
            </li>
          );
        })}
        {n > run.failing.length && <li className="text-muted-foreground">and {n - run.failing.length} more</li>}
      </ul>
    </>
  );
}
