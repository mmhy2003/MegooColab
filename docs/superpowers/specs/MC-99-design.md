# MC-99 — Build: record a test baseline and flag new failures early

## Goal

Before step 1 changes anything, the agent runs the project's full suite once and records which tests already fail. During Build, MegooColab compares every recorded test run with that baseline: a failing test that isn't in it is marked **new** for the implementer (at once, in the answer of `record_tests`), for the step reviewer and for people. A test that was already failing no longer holds a step up.

The approved mockup (v1) shows the four places where this is visible.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Who runs the baseline, and when | Step 1's implementer, before it changes anything. | You chose this. No new role and no extra agent session: the cost is one suite run. A separate baseline run (before step 1, or when the workflow starts) was rejected: an extra session per task, a new role with its own handler, nudge and escalation, and a 17th methodology text. A run at workflow start would also make tasks pay that never reach Build. |
| Cost | A project setting, **on by default**, also for existing projects. | You chose this. MegooColab can't know a suite's length before it runs, so "only short suites" is a person's choice. A task with 5 steps goes from about 6 full runs to 7. |
| What the baseline changes for a step | Flags, and rules for the agents. MegooColab blocks nothing itself. | You chose this. A step may be completed when the only failing tests are baseline ones; a new failure must be fixed first; for the step reviewer a new failure is a critical finding. "Flags only" was rejected (steps on a branch with old failures would keep asking a person). A refusal of `complete_step` by MegooColab was rejected: names are matched as text, and a differently written name would refuse a step wrongly. |
| Names in the baseline | The baseline run may name up to **100** failing tests; every other run keeps 20. | You chose this. When even 100 isn't all of them, the baseline is *incomplete*: nothing is called new, and steps need a green run or a person, as today. |
| The finish | Unchanged. The finish agent keeps its own check on the start commit (MC-97) and never sees the baseline. | You chose this. That check is minutes old, in the same environment, cheap, and works for tasks without a baseline. `finish.md` and the finish engine are not touched. |
| Where the flag shows | The answer of `record_tests`, the step reviewer's prompt, the plan's test run lines. | Follows from the choice above and mockup v1. |
| How the setting is frozen | A new column on the workflow, set when Build begins. | I told you the value is frozen when Build begins. It follows the frozen finish settings (`finish_tolerates_known`), and a task that was already in Build when you upgrade is never asked for a baseline or warned about one. |
| Marks in the reviewer's prompt | MegooColab writes the counts itself and lists the new tests in a block of their own. Marks are never written next to a name. | Test names are the agent's text. A name such as `test_x [also fails in the baseline]` could otherwise fake a mark. |
| A second baseline call | Allowed for step 1's implement run; the newest one counts. | An agent that first ran the suite with a broken environment (a service not started) can record a proper baseline after fixing it. It is trusted the way the first one is. |

## How it works

### Recording the baseline

1. When a plan is approved and Build begins (`documents._start_build`), a runner-driven workflow freezes the project's setting into `task_workflows.build_records_baseline`.
2. When the prompt of an `implement` run for step 1 is built, and the frozen value is true, and the task has no baseline yet, the prompt gets this section (MegooColab's own text):

   > **## Test baseline**
   > No baseline is recorded for this task yet. Before you change anything, run the project's full test suite and record that run with `record_tests(..., baseline=true)`. Do this only if the worktree is clean and the task branch has no commits of its own yet (`git status`, `git log`); otherwise skip it and carry on. See "The test baseline".

   The section is self-contained, so an installation with a customised `build_implement` text still gets a baseline.
3. The agent runs the suite and calls `record_tests(key, command, passed, total, failed, skipped, failing, baseline=true)`. A failing linter, type check or build counts as one failing test named after its command, as at finish.
4. `record_tests` accepts `baseline=true` only from a runner run with role `implement` at step 1, on a workflow whose frozen value is true. Anything else is refused with `baseline_not_allowed`.
5. If step 1's first review is queued and there is still no baseline, the event `build.no_baseline` is recorded once: "Step 1 finished without a test baseline: new failures won't be marked during Build". Nothing is blocked, and the finish check of MC-97 still applies.

A suite that can't run at all is not a baseline: the implementer asks a person, as "When you are blocked" already says.

### Comparing a run with the baseline

One pure function in `records.py` compares a test run with the task's baseline (the newest row with `baseline=true` since the workflow started):

- It applies to failed Build-stage runs that name at least one test. It doesn't apply to the baseline itself, to passing runs, to runs on the start commit (`on_base`), or to runs of the Review and Done stages.
- The baseline is **complete** when it passed, or when its `failed` count is not larger than the number of names it lists.
- Each failing name of the run gets one mark:
  - `baseline`: the name is in the baseline's list.
  - `new`: it is not, and the baseline is complete.
  - `unlisted`: it is not, and the baseline is incomplete.
- The run is **known-only** when every name is marked `baseline` and the run's own list is complete (its `failed` count is not larger than its list). A known-only run counts as a passing run for its step.
- Names are compared as exact text (they are trimmed when stored). The texts tell agents to write a test's name exactly as the baseline does, and the baseline's names are in their prompt.

### The implementer (`build_implement.md`, `build_step_fix.md`)

- `record_tests` answers at once. With a baseline, a failed run's answer gains `new_failing` (names), `baseline_failing` (a count), `unlisted_failing` (names, incomplete baseline only) and a `note`:
  - "1 failing test is new: it did not fail in the baseline. Fix it before you complete the step."
  - "Every failing test also fails in the baseline: none is new. The step's tests count as passing."
  - "The baseline lists only 100 of its 340 failing tests, so 1 failing test can't be compared. Treat it as yours unless you can show otherwise."
- A fresh prompt of `implement` and `step_fix` shows the baseline (see "Prompt sections").
- New section "The test baseline" in both texts, and these rule changes:
  - `tests_passed=true` means: you ran the tests and they passed, or the only failing tests are in the baseline and `record_tests` told you none is new.
  - A new failure is yours: fix it before `complete_step`. Never fix, skip or weaken a baseline test that the step doesn't touch.
  - In your own runs, name the tests that are not in the baseline first (a run names at most 20).
  - A test that passed in the baseline and now fails may be flaky: run it again and record that run.
- The tool lines of both texts show `baseline?`.

### The step reviewer (`build_step_review.md`)

After "Recorded test runs", the prompt has the baseline and MegooColab's comparison of the step's latest recorded run (see "Prompt sections"). The text's Tests check changes:

- A new failure in the step's latest run is a `critical` finding.
- A test that also fails in the baseline is not a finding.
- With an incomplete baseline, a failing test outside its list is treated as new unless the implementer's report shows otherwise.
- "A step that claims passing tests with no passing recorded run" becomes "…with no recorded run that passed or failed only baseline tests".

### The final reviewer (`review_final.md`)

It sees every step's runs, so it gets the baseline section too, and one changed sentence: a recorded run whose only failing tests are in the baseline counts as passing. It gets no comparison section: every step's comparison was already judged by its step reviewer.

### Prompt sections

Built in `records.py`, added by `engine.enqueue` as `extra_sections`. Agent-written text is wrapped as untrusted; the baseline's list is cut to `REPORTS_CHARS` with a line saying how many names were left out.

For `implement`, `step_fix`, `step_review` and `final_review`, when a baseline exists:

```
## Test baseline
Recorded before step 1, on the untouched task branch. 2 tests were already failing:
<untrusted source="test_baseline">
FAILED — uv run pytest -q -n auto (total 2186, failed 2)
tests/git/test_webhooks.py::test_gitlab_note_fix
tests/kb/test_embed.py::test_embed_retry
</untrusted>
```

A green baseline reads "No test was failing: every failing test is new." An incomplete one adds "(The baseline lists 100 of its 340 failing tests: a failing test outside this list can't be called new.)"

For `step_review` only, when the step's latest recorded run failed and can be compared:

```
## Compared with the test baseline
The step's latest recorded run has 3 failing tests: 1 new, 2 that also fail in the baseline.
New (not failing in the baseline):
<untrusted source="new_failures">
tests/workflow/test_context.py::test_prompt_within_limit
</untrusted>
```

With an incomplete baseline the second list is "Not in the baseline's list:" (source `unlisted_failures`). When the latest run is known-only: "…has 2 failing tests, and both also fail in the baseline. None is new."

A session that is resumed sees only its resume text, as today: a `step_fix` resumes the session that already saw the baseline in its `implement` prompt.

## Architecture

**Backend**

- `backend/app/workflow/records.py`
  - `record_tests(..., baseline: Any = False)`: validation, the 100-name limit for a baseline (`MAX_BASELINE_FAILING = 100`), the role and step check.
  - `baseline_run(db, wf)`: the task's newest baseline row since `wf.started_at`.
  - `compare(run, baseline)`: the marks and known-only, as above.
  - `baseline_section(baseline)` and `comparison_section(run, baseline)`.
  - `task_records` fills the new fields of `TestRunOut`.
  - `review_records` leaves baseline rows out of the reviewers' "Recorded test runs" (they have their own section).
  - `unverified_steps`: a claim is verified by a Build run of that step that passed **or is known-only**; baseline rows never verify a claim (the baseline is stored with stage Build and step 1).
- `backend/app/workflow/models.py`: `WorkflowTestRun.baseline`, `TaskWorkflow.build_records_baseline`.
- `backend/app/workflow/documents.py` (`_start_build`): freezes the setting for a runner-driven workflow.
- `backend/app/workflow/engine.py` (`enqueue`): adds the sections for the four roles; the "no baseline yet" section for `implement` at step 1.
- `backend/app/workflow/build.py` (`_handle_work`): the `build.no_baseline` event, next to `_warn_if_no_commit`, when step 1's first review is queued (`wf.review_round == 0`).
- `backend/app/workflow/schemas.py`: `TestRunOut.baseline`, `.marks`, `.known_only`.
- `backend/app/mcp_server/workflow_tools.py`: `record_tests` takes `baseline`, its docstring, and the richer answer.
- `backend/app/workflow/methodology_texts/defaults/`: `build_implement.md`, `build_step_fix.md`, `build_step_review.md`, `review_final.md`; their new hashes appended in `methodology_history.py`. The methodology keeps 16 keys.
- `backend/app/projects/` (`models.py`, `schemas.py`, `service.py`, `router.py`): the setting `record_test_baseline`, following `tolerate_known_test_failures`.
- One migration in `backend/migrations/versions/`.

`finish.py`, `finish.md`, `finish_fix.md` and `finish_fix_review.md` are not changed.

**Frontend**

- `frontend/src/components/workflow/TestBaseline.tsx` (new): the baseline box above the plan's steps: "Test baseline (before step 1) · 2 already failing — command" with the names; "✓ 2,184 passed" when green; "340 already failing, 100 listed" with the names folded when incomplete.
- `frontend/src/components/workflow/StepTestRun.tsx` (new): a step's latest run. Without marks it is today's line. Known-only: a muted "No new failures: 2 failed, both also fail in the baseline — command". Otherwise the pink line "✗ 3 failed, 1 new — command" and the list of names with a tag each (`new` in pink, `also fails in the baseline`, `not in the baseline's list`), then "and N more" when the run names fewer tests than failed.
- `frontend/src/components/workflow/DocumentView.tsx`: uses both; a step's runs leave the baseline row out.
- `frontend/src/lib/workflow.ts`: `testRunText` adds "(1 new)" for the one-line form in "Earlier runs"; the mark labels; the setting's label and help text.
- `frontend/src/components/task/ActivityThread.tsx`: the text of `build.no_baseline`.
- `frontend/src/components/project/WorkflowSettings.tsx`: the checkbox and its read-only line, after "Finish when the only failing tests are known ones".
- `frontend/src/lib/api-types.ts`: regenerated with `npm run gen:api`.

## Data and interfaces

**MCP tool**

- `record_tests(key, command, passed, total?, failed?, skipped?, failing?, on_base?, baseline?)`.
  - `baseline=true`: this run is the task's test baseline. Up to 100 names. With `passed=false`, `failed` is required (`invalid_record` without it). Together with `on_base=true` it is refused (`invalid_record`). From anything but a runner `implement` run at step 1 with the frozen setting on: `baseline_not_allowed`.
  - Answer: `{id, passed}` as today; `baseline: true` for a baseline; and for a compared run `new_failing`, `baseline_failing`, `unlisted_failing` and `note`.

**Database (one migration)**

- `projects.record_test_baseline`: boolean, not null, default true.
- `task_workflows.build_records_baseline`: boolean, nullable. Set when Build begins; null for workflows that began Build earlier and for connect-only ones.
- `workflow_test_runs.baseline`: boolean, not null, default false.

**API**

- `TestRunOut.baseline: bool`, `TestRunOut.marks: list["new" | "baseline" | "unlisted"] | null` (one per name in `failing`; null when the run isn't compared), `TestRunOut.known_only: bool`.
- `ProjectOut` and the project PATCH body: `record_test_baseline`.

**Event on the task**

- `build.no_baseline` `{}`.

**Setting's text**

- Label: "Record a test baseline when Build starts".
- Help: "On: before step 1 changes anything, the agent runs the full test suite once and records which tests already fail. During Build, a failing test that isn't in that baseline is marked new for the agent, the step reviewer and you, and a test that was already failing doesn't hold a step up. This costs one more full run per task. Off: no baseline, and every step needs a fully green run."

## Error handling and edge cases

- **No baseline** (setting off, the agent skipped it, a customised text, a task already in Build at the upgrade, connect-only): no sections, no marks, no change in the tool's answer. Build works exactly as today.
- **Step 1 runs again** (a retry after a failed run, or a resume after a pause). The prompt asks for a baseline only while none exists, and tells the agent to record one only on a clean worktree with no commits of the task. It never stashes or undoes work to get one.
- **Incomplete baseline** (more than 100 failing, or a failed baseline that names no tests): no test is called new; names outside the list are marked "not in the baseline's list"; a run is never known-only unless all its names are in the list.
- **A step's run names 20 of more failures**: the listed names are marked; the run is not known-only.
- **A name written differently than in the baseline**: it is marked new. The implementer sees that at once in the tool's answer and can record the run again with the baseline's spelling; the reviewer judges what remains. Nothing is refused by MegooColab.
- **A flaky test**: one that failed in the baseline and passes later is harmless. One that passed in the baseline and fails in a step is marked new; the implementer runs it again and records the passing run.
- **The branch fixes or removes a baseline test**: its name simply no longer appears.
- **A baseline row and step 1's own runs**: the baseline row is kept out of step 1's test run lines, out of "Recorded test runs" and out of the check for unverified claims, so a green baseline never proves step 1's claim.
- **The setting changes during Build**: the frozen value decides.
- **Agent-written text** (test names, the command) is plain text in the UI and wrapped as untrusted in prompts; MegooColab's statements about it stand outside the wrapper.
- **Prompt size**: the baseline's list is cut to the usual 8,000 characters with a note; the comparison lists at most 20 names.
- **Freestyle rounds, pull request fix rounds, fix rounds at finish and the finish run**: not compared, not changed.

## Testing

**Backend (`megoocolab-runner services run test -- uv run pytest …`)**

- `tests/workflow/test_records.py`
  - `baseline=true` is stored and returned; 100 names pass and 101 are refused; 21 names without the flag are still refused.
  - Refused with `baseline_not_allowed` from step 2, from `step_fix`, from a finish run, from a connect-only agent, and when the frozen value is false or null.
  - `invalid_record` for a non-boolean, for `on_base` together with `baseline`, and for a failed baseline without `failed`.
  - The newest baseline counts.
  - `compare`: a green baseline (all new), a complete one (new and baseline marks), an incomplete one (unlisted), known-only, a run with an incomplete list, and the runs that aren't compared.
  - `unverified_steps`: a known-only run verifies a claim; a baseline row doesn't.
  - `baseline_section` and `comparison_section`: the three baseline states, the cut list, and a name that tries to fake a mark stays inside the wrapper.
  - `/records` returns `baseline`, `marks` and `known_only`.
- `tests/workflow/test_documents.py`: approving the plan freezes the setting; a connect-only workflow keeps null.
- `tests/workflow/test_engine.py` or `test_context.py`: the "no baseline yet" section only for `implement` at step 1 with the frozen value on and no baseline; the baseline section for the four roles; the comparison section for `step_review` only; none of them at finish.
- `tests/workflow/test_build.py`: `build.no_baseline` once, when step 1's first review is queued without a baseline; not on later rounds, not for step 2, not with the value off.
- `tests/mcp/test_workflow_tools.py`: the tool's answer in the three cases, and unchanged without a baseline.
- `tests/workflow/test_methodology.py`: the history ends with the four new texts.
- `tests/projects/test_projects.py`: PATCH and read of the setting; a non-manager gets 403.
- The migration goes up, down and up again.

**Frontend**

- Vitest: `testRunText` with marks; `TestBaseline` (failing, green, incomplete); `StepTestRun` (no marks, known-only, new, unlisted, "and N more"); `DocumentView` (the baseline box, the baseline row not among step 1's runs); the `ActivityThread` text; `WorkflowSettings`.
- `npx tsc --noEmit`, `npx eslint <changed files>`, `npm test`.
- Playwright: one case in `e2e/workflow.spec.ts`, driven as that spec already drives a workflow: step 1 records a baseline with one failing test, step 1's run fails that test and one more, and the plan shows the baseline box, one `new` tag and one `also fails in the baseline` tag.

## Out of scope

- A baseline at finish: the finish keeps its own check on the start commit (MC-97).
- A separate baseline run or role, and a baseline before the brainstorm.
- MegooColab refusing `complete_step` on a new failure.
- Baselines for connect-only workflows and freestyle rounds.
- Comparing the runs of the final fix, of pull request fix rounds and of fix rounds at finish.
- An organisation-wide default for the new setting. New and existing projects start with it on.
- Offering bug tasks for tests that fail in the baseline (already a follow-up of MC-97).
