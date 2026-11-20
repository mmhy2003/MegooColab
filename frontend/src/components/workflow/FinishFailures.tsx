"use client";

import Link from "next/link";

import { Button } from "@/components/ui/Button";
import {
  failureKindLabel, type FinishTests, finishedWithSummary, finishTestsSummary, type TestRun, testRunText,
} from "@/lib/workflow";

const bugHref = (key: string) => `/projects/${key.replace(/-\d+$/, "")}/board?task=${key}`;

/** The finish run's failing tests (MC-97): a summary, each test with its kind, the agent's diagnosis and the test runs
 * it recorded at finish. On the "Tests failed at finish" card and, once the finish settled, in the workflow panel;
 * the panel's box for a running fix round (MC-98) leaves the diagnosis out with `showDiagnosis={false}`.
 * A base or flaky row links to the project's open bug for the test (MC-100) or, with `onCreateBug`, offers one; never
 * a new row. Test names and the diagnosis are agent-written: shown as plain text only. */
export function FinishFailures({
  tests, startBranch, runs = [], showDiagnosis = true, taskKey, onCreateBug, busy = false,
}: {
  tests: FinishTests;
  startBranch: string | null;
  runs?: TestRun[];
  showDiagnosis?: boolean;
  taskKey?: string;
  onCreateBug?: (name: string) => void;
  busy?: boolean;
}) {
  const failures = tests.failures ?? [];
  const more = (tests.failing_total ?? 0) - failures.length;
  return (
    <div className="space-y-1">
      <p>{tests.settled ? finishedWithSummary(tests, startBranch) : finishTestsSummary(tests, startBranch)}</p>
      {failures.length > 0 && (
        <ul aria-label="Failing tests" className="space-y-0.5 text-xs">
          {failures.map((f, i) => (
            <li key={`${i}-${f.name}`}>
              <code className="break-all">{f.name}</code>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                <span className="rounded border px-1 text-muted-foreground">{failureKindLabel(f.kind, startBranch)}</span>
                {f.bug ? (
                  f.bug.key === taskKey ? (
                    <span className="text-muted-foreground">Bug: this task</span>
                  ) : (
                    <Link href={bugHref(f.bug.key)} title={f.bug.title} className="text-cyan-ink underline">Bug: {f.bug.key}</Link>
                  )
                ) : (
                  onCreateBug && f.kind !== "new" && (
                    <Button variant="ghost" disabled={busy} onClick={() => onCreateBug(f.name)}>Create bug task</Button>
                  )
                )}
              </div>
            </li>
          ))}
          {more > 0 && <li>and {more} more</li>}
        </ul>
      )}
      {showDiagnosis && tests.diagnosis && (
        <>
          <p className="text-xs text-muted-foreground">Diagnosis</p>
          <p className="whitespace-pre-wrap text-xs">{tests.diagnosis}</p>
        </>
      )}
      {runs.length > 0 && (
        <details className="text-xs">
          <summary>Test runs at finish ({runs.length})</summary>
          <ul>{runs.map((r) => <li key={r.id}>{testRunText(r)}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
