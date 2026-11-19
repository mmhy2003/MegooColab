# MC-97 — Finish stage: known test failures don't block, and a person can accept the rest

## Goal

A task no longer gets stuck in Done because its finish run saw failing tests. A test that already fails on the commit the branch started from, or that passes when it is run again, doesn't stop the finish. Any other failure goes to a person on a clear decision card with **Finish anyway**, **Retry** and **Pause**.

This design covers pieces 1, 2, 3 and 5 of the task. Pieces 4 and 6 and the bug task offers are follow-up tasks (see "Out of scope").

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Scope | Pieces 1, 2, 3 and 5 now. The fix round (4), early detection (6) and bug task offers are follow-ups. | You chose this. The four pieces share the same parts: the agent's failure report, the engine's handling of it and the card. |
| Where the baseline comes from | The finish agent checks it at finish, only for tests that still fail after re-runs, on the commit the task branch started from (the merge-base with the start branch). | You chose this. No cost when the suite is green, and the comparison is the same tests in the same environment, minutes apart. A full baseline run before Build was rejected (every task pays a full run; the result is stale names). Project CI was rejected (another environment; not every project has one). |
| Known failures | The finish goes on without asking. A project setting, on by default, turns that off. | You chose this. |
| How the person decides on other failures | A decision card (a new escalation, `finish_tests_failed`) fed by a structured report from the agent. | You chose this over an `ask_human` question with fixed choices. Failures become data, and the follow-up's "Fix round" button fits on the same card. |
| Bug tasks for known failures | Follow-up task. | You chose this. A good offer must recognise a test that already has an open bug task in the project. |
| How a test is identified | By the name the agent reports, as in `record_tests` (up to 20 names, 300 characters each). | The agent classifies inside one finish session, re-running the same tests, so the engine never has to match names between a baseline and a later run. The engine compares names only between an accepted card and the report that follows it in the same session. |
| Structured fields or engine comparison | `report_finish` gains structured `failures`; the engine doesn't derive kinds from recorded runs. | Passing runs carry no test names, so the engine can't tell a flaky test from the records. The classification is trusted the way `tests_passed` is trusted today. The recorded runs stay on the task as evidence. |
| Tasks stuck today (like MC-81) | A migration turns `finish_incomplete` into `finish_tests_failed` where the finish run had already delivered. | Those tasks then show the card with Finish anyway. `finish_incomplete` keeps its text, which is now accurate: it is raised only when the run reported nothing. |

## How it works

### The finish agent (methodology text `finish.md`)

Step 1 changes. The agent runs the full suite and records it, as today. If something fails:

1. **Flaky check.** It re-runs the failing tests together, up to two more times, and records each run. A test that passes in a re-run is `flaky`.
2. **Start commit check.** For tests that still fail, with a clean tree, it finds the merge-base with the start branch, runs `git switch --detach <commit>`, runs only those tests, records the run with `on_base=true`, switches back to the task branch and confirms the tree is clean. A test that fails there too is `base`. No file is edited, so the rule that the finish agent never changes code holds.
3. Every other failure is `new`. That includes a test that can't be run on the start commit (for example because its dependencies differ). A failing linter, type check or build counts as one failing test named after its command.
4. **Only known failures, and the prompt says they are tolerated:** the agent carries out the finishing option. The pull request description gets a "Known failing tests" section: "Already failing on &lt;start branch&gt;" and "Flaky (passed when run again)". It ends with `report_finish(..., tests_passed=false, failures=[...])`.
5. **Anything else:** the agent delivers nothing. It diagnoses as "When something fails" says, calls the new tool `report_test_failures(key, failures, diagnosis)` and ends its turn. It no longer uses `ask_human` for failing tests; `ask_human` stays for other blockers (a missing CLI, a dirty main checkout).
6. **Resumed after "Finish anyway":** it carries out the finishing option, lists the tests in the pull request description as accepted by that person, and calls `report_finish` with `tests_passed=false` and the same `failures`.

Also new in the text:

- `merge_local`: when the tests on the merged result show a failing test that step 1 did not classify, the agent undoes its merge and calls `report_test_failures`.
- When the task branch's pull request already exists (a retry after a delivery), the agent pushes and reports that pull request's URL without opening another.
- `tests_passed` is true only when the last full run was green.

### The engine (`finish._handle_finish`)

| The finish run ended with | Condition | Result |
| --- | --- | --- |
| `report_finish`, `tests_passed=true` | | Moves on as today (waits for the pull request, or finishes). |
| `report_finish`, `tests_passed=false` | Every failure is `base` or `flaky`, the list is complete, and the frozen setting tolerates them | Event `finish.known_failures`; moves on. |
| same | Every failure that needs a person is among the names accepted on the card | Moves on. |
| same | The run resumes the session of a finish run whose question a person answered | That answer counts as the acceptance (event `finish.failures_accepted`, by the answerer); moves on. This is the task's "go ahead anyway" case, and it covers agents on an older or customised finish text. |
| same | Otherwise | Escalation `finish_tests_failed`, marked as delivered. No nudge: a nudge can't change a delivered result. |
| `report_test_failures` | | Escalation `finish_tests_failed`, marked as not delivered. |
| Neither | | One nudge, then `finish_incomplete`, as today. |

"Needs a person" means: `new` failures; every failure when the setting is off; every failure when `failing_total` says more tests fail than the list names. A report with `tests_passed=false` and no names is covered by any acceptance in this Done round.

"Moves on" is the existing `tests_passed` branch of `_handle_finish`, extracted into one helper (`_move_on`) that the handler and the accept handler share.

### The decision card (escalation `finish_tests_failed`)

- **Finish anyway** (`accept`): `finish._accept_tests_failed` records who accepted and which tests (on the workflow, an event and an audit entry).
  - Already delivered: the workflow moves on.
  - Not delivered: a finish run is queued that resumes the reporting run's session (`resume_session_ref`, as `questions.deliver` does for fresh roles) with a text that names the person and the accepted tests and says to deliver and report. The test names are the agent's own text, so they go in an untrusted block.
- **Retry** (`RETRY_HANDLERS["finish_tests_failed"]`): clears the stored failures and acceptance, then starts a fresh finish run, as Retry does today.
- **Pause**: unchanged.

A new report replaces the stored failures and clears an earlier acceptance. If the resumed run reports a failing test the person didn't accept (for example after a local merge), the card comes back with the new list.

## Architecture

**Backend**

- `backend/app/workflow/finish.py`: `report_finish` takes `failures` and `failing_total`; new `report_test_failures`; `_handle_finish` as in the table; `_move_on`; `_accept_tests_failed`; the retry handler; `enter_done` freezes the setting and clears `wf.finish_tests`; the module docstring's Done section.
- `backend/app/workflow/engine.py`: the finish prompt's "Finishing" section gains one line, `Known failing tests: tolerated` or `not tolerated`. `_pending_need` treats a settled finish like passing tests, so a pause and resume returns to the pull request wait and doesn't run finish again. The comment above `ACCEPT_HANDLERS` is updated.
- `backend/app/workflow/records.py`, `models.py`: `record_tests` takes `on_base`; reviewers' and people's lines mark such a run "on the start commit".
- `backend/app/mcp_server/workflow_tools.py`: the `report_test_failures` tool (finish role only, runner only), the new parameters of `report_finish` and `record_tests`, and the finish line of `RUN_NEXT`.
- `backend/app/workflow/methodology_texts/defaults/finish.md` and `methodology_history.py` (the new text's hash, so installations that never customised the text get it as a new version). `pr_fix.md` and `review_fix.md` only if they describe `record_tests`' parameters in a way that would now be wrong.
- `backend/app/workflow/schemas.py`, `router.py`: `WorkflowOut.finish_tests`; `TestRunOut.on_base`.
- `backend/app/projects/` (`models.py`, `schemas.py`, `service.py`, `router.py`): the project setting, following `send_back_on_changes_requested`.
- One migration in `backend/migrations/versions/`.

**Frontend**

- `frontend/src/components/workflow/FinishFailures.tsx` (new): the summary line, the tagged list, the diagnosis and the Done stage's recorded test runs. It is used on the card and, after the finish, in the workflow panel ("Finished with 2 known failing tests").
- `EscalationActions.tsx`: for `finish_tests_failed` it shows `FinishFailures`, labels Accept "Finish anyway" and adds the hint line. Other reasons are unchanged.
- `WorkflowPanel.tsx`: shows `FinishFailures` once the finish is settled with failures.
- `frontend/src/lib/workflow.ts`: `ESCALATION_REASON_TEXT.finish_tests_failed`, `ACCEPTABLE_REASONS`, the summary text function ("Tests failed at finish: 3 failing (1 new, 1 also fails on develop, 1 flaky)"), the kind labels, the setting's help text, and `testRunText` marking a run on the start commit.
- `ActivityThread.tsx`: texts for the three new events.
- `WorkflowSettings.tsx`: the checkbox and its read-only line.
- `frontend/src/lib/api-types.ts`: regenerated with `npm run gen:api`.

## Data and interfaces

**MCP tools**

- `report_finish(..., failures?, failing_total?)`. `failures` is at most 20 entries of `{name, kind}`; `name` is at most 300 characters; `kind` is `new`, `base` or `flaky`. `failing_total` is how many tests fail in all, when that is more than the list names. `tests_passed=true` with failures, or a malformed entry, is refused with `invalid_finish_result`; oversize with `too_large`.
- `report_test_failures(key, failures, diagnosis, failing_total?)`: `failures` as above and required (at least one); `diagnosis` is text of at most 2,000 characters. A later call from the same run replaces the earlier one, and so does a `report_finish` from the same run.
- `record_tests(..., on_base?)`: true for a run made on the start commit. Default false.

**Database (one migration)**

- `projects.tolerate_known_test_failures`: boolean, not null, default true.
- `task_workflows.finish_tolerates_known`: boolean, nullable. Frozen when Done begins; a row from before falls back to the project's setting, as the other frozen finish fields do.
- `task_workflows.finish_tests`: JSONB, nullable: `{failures, failing_total, diagnosis, delivered, accepted_by, accepted_at, accepted (names), settled}`. `settled` is null, `"known"` or `"accepted"`. Null until a finish reports failing tests; cleared when Done begins and on Retry.
- `workflow_test_runs.on_base`: boolean, not null, default false.
- Data fix: every workflow in stage Done with `escalation_reason = 'finish_incomplete'` whose newest finish run reported an outcome gets `escalation_reason = 'finish_tests_failed'` and `finish_tests = {"failures": [], "delivered": true}`. Paused ones too, because a pause keeps the reason. The downgrade turns them back.

**API**

- `WorkflowOut.finish_tests`: `{failures: [{name, kind}], failing_total, diagnosis, delivered, settled, accepted_by (the person's name)}` or null.
- `TestRunOut.on_base`.
- `ProjectOut` and the project PATCH body: `tolerate_known_test_failures`.
- `POST /api/tasks/{key}/workflow/escalation` is unchanged: `accept` now also applies to `finish_tests_failed`.

**Events on the task**

- `finish.tests_failed` `{failures, failing_total, delivered}`: "Tests failed at finish: 3 failing (1 new, 1 also fails on develop, 1 flaky)".
- `finish.known_failures` `{failures}`: "Finished with 2 known failing tests: 1 also fails on develop, 1 flaky".
- `finish.failures_accepted` `{failures, via}` with the person as actor; `via` is `card` or `answer`: "accepted 3 failing tests: …".
- Audit: `workflow.finish_failures_accepted` with the names, next to the existing `workflow.accept`.

## Error handling and edge cases

- **More than 20 failing tests.** The list can't cover them, so they are never tolerated automatically: the card shows the 20 names and "and N more".
- **The agent names no tests** (`tests_passed=false` without `failures`: an older text, or no tests were run). The card's first line is "The agent reported that the tests did not pass." and there is no list. Finish anyway and Retry work as usual.
- **The setting is off.** The prompt says "not tolerated". The agent still classifies and reports every failure with `report_test_failures`, so the card shows the kinds. Finish anyway covers all of them.
- **The setting changes during Done.** The frozen value decides, as for the finishing option.
- **Customised finish text.** It is never overwritten. Such an agent keeps asking with `ask_human`; the answered-question rule and the delivered card keep the task from getting stuck.
- **The answered-question rule.** It counts any answer in that finish session, because the engine can't read a free-text answer. An agent delivers with failing tests only after a person told it to, so a "no" answer leads to no report. The event names the answerer, so the acceptance is visible on the task.
- **The agent is left on the start commit** (it stopped between the two switches). The text tells it to confirm the task branch before anything else, as step 1 already requires. A fresh run after Retry begins with the same check.
- **The resumed run ends without a report.** One nudge, then `finish_incomplete`, as today.
- **No session to resume** (the reporting run had no session id). The acceptance text goes at the end of a fresh finish prompt; `engine.enqueue` already does this for a resume text without a session.
- **Pause and resume after a settled finish.** `_pending_need` returns to the pull request wait.
- **Pull request fix rounds** (`pr_fix`) return to Done without `enter_done`, so `finish_tests` and its `settled` value stay.
- **Agent-written text** (test names, the diagnosis) is shown as plain text in the UI and wrapped as untrusted in prompts.
- **Retry after a delivery.** The fresh finish run finds the existing pull request and reports it.
- Connect-only and manual workflows and freestyle rounds have no finish runs and are unaffected.

## Testing

**Backend (`uv run pytest`)**

- `tests/workflow/test_review_done.py`: one case per row of the engine table. The existing "failing tests → nudge → `finish_incomplete`" test changes: a delivered report with failing tests now escalates `finish_tests_failed` at once, and the no-report path still nudges once and then escalates `finish_incomplete`.
- Accept: delivered (with and without required review), and not delivered (the queued run resumes the session with the text; its report then finishes). A report with a test outside the accepted names brings the card back.
- Retry clears the stored state. Pause and resume after a settled finish waits for the pull request.
- The setting: off blocks known failures; it is frozen at `enter_done`; a null frozen value falls back to the project.
- The answered-question rule: accepted and attributed to the answerer; an answer in another session doesn't count.
- Validation of `failures`, `failing_total`, `diagnosis`; `report_test_failures` refused outside the finish role and for connect-only workflows.
- `tests/workflow/test_records.py`: `on_base` is stored, returned and marked in the reviewers' line.
- `tests/workflow/test_methodology.py`: the history ends with the new `finish.md`.
- A migration test in the style of `test_merge_confirmation_migration.py` for the data fix.
- Project API: PATCH and read of the setting.

**Frontend**

- Vitest: the summary text (counts, singular and plural, no names, "and N more"), `EscalationActions` for the new reason in both states, `FinishFailures`, the `ActivityThread` texts, `WorkflowSettings`, `testRunText` with `on_base`.
- `tsc --noEmit`, eslint, `npm test`.
- Playwright: one case in `e2e/workflow.spec.ts`, driven the way that spec already drives a workflow: a finish that reports a new failure shows the card, and Finish anyway finishes the workflow.

## Out of scope

- A "finish fix" round for failures the branch caused (piece 4): follow-up task.
- A baseline before Build and flagging new failures during Build (piece 6): follow-up task.
- Offering bug tasks for known failures: follow-up task.
- An organisation-wide default for the new setting. New projects start with it on.
- Cross-checking the agent's classification against the recorded runs.
- The notification title for an escalation, which keeps showing the reason code, as for every other reason.
- Failing tests in pull request fix rounds (`pr_fix_incomplete` already has Accept).