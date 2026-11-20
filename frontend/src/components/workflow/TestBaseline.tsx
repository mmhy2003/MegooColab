import type { TestRun } from "@/lib/workflow";

/** The task's test baseline (MC-99): the full suite before step 1 changed anything, and the tests that already failed. */
export function TestBaseline({ run }: { run: TestRun }) {
  const head = "Test baseline (before step 1)";
  if (run.passed) {
    const passed =
      run.total != null ? `✓ ${(run.total - (run.failed ?? 0) - (run.skipped ?? 0)).toLocaleString("en-US")} passed` : "✓ passed";
    return (
      <section aria-label="Test baseline" className="card space-y-1 p-2 text-xs">
        <p>
          {head} · {passed} — {run.command}
        </p>
      </section>
    );
  }
  const n = run.failed ?? run.failing.length;
  const complete = n <= run.failing.length;
  const names = (
    <ul className="ml-3 text-muted-foreground">
      {run.failing.map((name) => (
        <li key={name}>{name}</li>
      ))}
    </ul>
  );
  return (
    <section aria-label="Test baseline" className="card space-y-1 p-2 text-xs">
      <p>
        {head} · {n} already failing{complete ? "" : `, ${run.failing.length} listed`} — {run.command}
      </p>
      {complete ? (
        names
      ) : (
        <details>
          <summary>Listed tests ({run.failing.length})</summary>
          {names}
        </details>
      )}
    </section>
  );
}
