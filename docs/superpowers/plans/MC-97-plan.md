# MC-97 implementation plan: known test failures don't block the finish, and a person can accept the rest

**Goal:** a task no longer gets stuck in Done because its finish run saw failing tests. Tests that are flaky or that also fail on the start commit don't stop the finish. Any other failure goes to a person on a "Tests failed at finish" card with **Finish anyway**, **Retry** and **Pause**.

**Architecture:** the finish agent sorts its failing tests into `new`, `base` or `flaky` (methodology text `finish.md`). It then reports them through `report_finish(..., failures, failing_total)`, which means it delivered, or through the new `report_test_failures(...)`, which means it delivered nothing. `finish.py` stores the report on `task_workflows.finish_tests` (JSONB). `_handle_finish` either moves on through a shared `_move_on` helper or raises the new escalation `finish_tests_failed`. That escalation has an accept handler and a retry handler. A project setting, `tolerate_known_test_failures`, is frozen into `task_workflows.finish_tolerates_known` when Done begins. The frontend shows the report with a new `FinishFailures` component, on the escalation card and, after the finish, in the workflow panel.

## Conventions for every step

- Branch `megoo/MC-97-finish-stage-don-t-get-stuck-on-test-fai`. One commit per step. Subject: `type(area): what changed (MC-97)` (AGENTS.md "Commits"). The body says why. It ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and watch it fail, implement, then run it again and watch it pass.
- Backend commands run from `backend/`: `megoocolab-runner services run test -- uv run pytest <paths> -q`. Never run two pytest commands at once. Before each backend commit, run the files the step touched plus `tests/workflow tests/mcp` with `-q -n auto`.
- Frontend commands run from `frontend/`: `npx vitest run <files>`, then `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`. Run `npm ci` first if `node_modules` is missing. Don't reformat files you don't otherwise change.
- Migrations run from `backend/`: `megoocolab-runner services run migrate -- bash scripts/makemigration.sh "<message>"`.
- Agent-written text (test names, the diagnosis) is shown as plain text in the UI and wrapped as untrusted in prompts.
- Names shared across steps:
  - Kinds: `KINDS = ("new", "base", "flaky")`.
  - Escalation reason: `"finish_tests_failed"`.
  - Events: `finish.tests_failed`, `finish.known_failures`, `finish.failures_accepted`.
  - Audit action: `workflow.finish_failures_accepted`.
  - Resume kind: `"failures_accepted"`.
  - `wf.finish_tests` keys: `failures` (list of `{name, kind}`), `failing_total` (int|None), `diagnosis` (str|None), `delivered` (bool), `settled` (None|"known"|"accepted"), `accepted_by` (user id str), `accepted_at` (ISO str), `accepted` (list of names).

## File map

| File | Change |
|---|---|
| `backend/app/projects/models.py` | `Project.tolerate_known_test_failures` (bool, default true) |
| `backend/app/workflow/models.py` | `TaskWorkflow.finish_tolerates_known`, `TaskWorkflow.finish_tests`; `WorkflowTestRun.on_base` |
| `backend/migrations/versions/<rev>_finish_test_failures.py` (new) | the columns, `UP_SQL` data fix, `DOWN_SQL` |
| `backend/app/projects/schemas.py`, `service.py`, `router.py` | the setting in `ProjectOut`, `ProjectPatch` and PATCH |
| `backend/app/workflow/records.py`, `schemas.py` | `record_tests(on_base)`, `TestRunOut.on_base`, the reviewers' line |
| `backend/app/workflow/finish.py` | failures validation, `report_finish` fields, `report_test_failures`, `_move_on`, the new `_handle_finish`, `_accept_tests_failed`, `_retry_tests_failed`, `enter_done` freeze, docstring |
| `backend/app/workflow/engine.py` | `tolerates_known()`, the "Known failing tests" prompt line, `_pending_need`, the `ACCEPT_HANDLERS` comment |
| `backend/app/workflow/context.py` | `resume_text("failures_accepted", …)`; `RESUME_HEADING` entry lives in engine.py |
| `backend/app/mcp_server/workflow_tools.py` | `report_test_failures` tool, new params of `report_finish` and `record_tests`, `TOOL_ROLES`, `RUNNER_ONLY`, `RUN_NEXT[finish]` |
| `backend/app/workflow/schemas.py`, `router.py` | `FinishFailureOut`, `FinishTestsOut`, `WorkflowOut.finish_tests` |
| `backend/app/workflow/methodology_texts/defaults/finish.md`, `methodology_history.py` | the new text and its hash |
| `backend/tests/workflow/test_finish_failures.py` (new) | engine and tool tests for this task |
| `backend/tests/workflow/test_finish_tests_migration.py` (new) | data fix test |
| `backend/tests/workflow/test_review_done.py`, `test_records.py`, `test_methodology.py`, `tests/mcp/test_workflow_tools.py`, `tests/mcp/test_mcp.py`, `tests/projects/test_projects.py` | updated or extended tests |
| `frontend/src/lib/api-types.ts` | regenerated |
| `frontend/src/lib/workflow.ts` | reason text, `ACCEPTABLE_REASONS`, `FinishTests` type, `failureKindLabel`, `finishTestsSummary`, `finishedWithSummary`, `TOLERATE_KNOWN_HELP`, `testRunText` on_base |
| `frontend/src/components/workflow/FinishFailures.tsx` (new) | summary, tagged list, "and N more", diagnosis, Done-stage test runs |
| `frontend/src/components/workflow/EscalationActions.tsx` | the `finish_tests_failed` variant |
| `frontend/src/components/workflow/WorkflowPanel.tsx` | passes runs; shows `FinishFailures` once settled |
| `frontend/src/components/task/ActivityThread.tsx` | texts for the three events |
| `frontend/src/components/project/WorkflowSettings.tsx` | checkbox and read-only line |
| `frontend/e2e/workflow.spec.ts` | the finish reports a new failure; Finish anyway finishes |

---

## Step 1: Add the columns and the migration that moves stuck tasks to finish_tests_failed

**Files:** `backend/app/projects/models.py`, `backend/app/workflow/models.py`, new `backend/migrations/versions/<rev>_finish_test_failures.py`, new `backend/tests/workflow/test_finish_tests_migration.py`.

**Models:**
- `Project.tolerate_known_test_failures: Mapped[bool] = mapped_column(default=True, server_default=true())`. Import `true` from sqlalchemy next to `false`. Comment it as MC-97: a test failing on the start commit, or a flaky one, doesn't stop the finish.
- In `TaskWorkflow`, after `finish_pr_review`:
  ```python
  # frozen with them (MC-97): known failing tests (start commit, flaky) don't stop the finish. None before Done
  finish_tolerates_known: Mapped[bool | None]
  # the finish run's failing tests (MC-97): {failures, failing_total, diagnosis, delivered, settled, accepted_by,
  # accepted_at, accepted}; None until a finish reports failing tests, cleared when Done begins and on Retry
  finish_tests: Mapped[dict | None] = mapped_column(JSONB)
  ```
- `WorkflowTestRun.on_base: Mapped[bool] = mapped_column(default=False, server_default=false())`, with the comment "run on the commit the task branch started from".

**Migration:** run `megoocolab-runner services run migrate -- bash scripts/makemigration.sh "finish_test_failures"`. Check that its `down_revision` is `'b215d4e16f2d'` and that it adds exactly these 4 columns. Then add the data fix as module constants, following `9293a24ba936_merge_confirmation_waits.py`:

```python
# Tasks stuck on finish_incomplete although the finish run delivered (it reported failing tests) get the new
# decision card, which offers Finish anyway. Paused ones too: a pause keeps the reason.
UP_SQL = """
UPDATE task_workflows w
SET escalation_reason = 'finish_tests_failed',
    finish_tests = jsonb_build_object('failures', jsonb_build_array(), 'delivered', true)
WHERE w.stage = 'done' AND w.escalation_reason = 'finish_incomplete'
  AND (
      SELECT r.step_result->>'outcome' FROM agent_runs r
      WHERE r.task_id = w.task_id AND r.workflow_role = 'finish'
      ORDER BY r.created_at DESC, r.id DESC LIMIT 1
  ) IS NOT NULL
"""
DOWN_SQL = """
UPDATE task_workflows SET escalation_reason = 'finish_incomplete' WHERE escalation_reason = 'finish_tests_failed'
"""
```

`upgrade()` adds the columns, then runs `op.execute(UP_SQL)`. `downgrade()` runs `op.execute(DOWN_SQL)` first, then drops the columns.

**Test first:** `tests/workflow/test_finish_tests_migration.py`, in the style of `test_merge_confirmation_migration.py`. Load the module with the glob `*_finish_test_failures.py`. Set up one board with `tests.workflow.test_engine._started(db, tc)`; it gives a task, its run, the agent and `b.manager`. Create more tasks with `tc.post("/api/projects/PAY/tasks", ...)`. For each task, add a `TaskWorkflow` and finish `AgentRun` rows that copy the required fields (`agent_id`, `requested_by`, `policy`, `prompt`, `status`) from the started run.
- `test_stuck_finish_with_a_delivery_moves_to_the_card`: covers Done + `finish_incomplete` with the newest finish run's `step_result={"outcome": "pr_opened", ...}`, in two variants: status `waiting_human` and status `paused`. Both get `escalation_reason == "finish_tests_failed"` and `finish_tests == {"failures": [], "delivered": True}`.
- These stay unchanged:
  - the newest finish run has `step_result=None`, even though an older one reported;
  - the stage is `review` with `review_incomplete`;
  - Done with another reason (`pr_closed`).
- `test_downgrade_sql_puts_the_reason_back`: `"finish_incomplete" in DOWN_SQL`.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_tests_migration.py -q`. It fails before the migration exists and passes after.

**Also check:** `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`.

**Commit:** `feat(workflow): store finish test failures and the known-failures setting (MC-97)`.

## Step 2: Expose the project setting tolerate_known_test_failures in the projects API

**Files:** `backend/app/projects/schemas.py`, `service.py`, `router.py`, `backend/tests/projects/test_projects.py`.

Follow `send_back_on_changes_requested` exactly:
- `ProjectPatch.tolerate_known_test_failures: bool | None = None`.
- `ProjectOut.tolerate_known_test_failures: bool`.
- `service.py` passes `tolerate_known_test_failures=project.tolerate_known_test_failures` to `ProjectOut`.
- `router.py`, next to line 135: `if body.tolerate_known_test_failures is not None: project.tolerate_known_test_failures = body.tolerate_known_test_failures`.

**Test first** in `tests/projects/test_projects.py`, next to the send-back test at line 160: `test_tolerate_known_test_failures_setting`.
- A new project returns `True`.
- PATCH `{"tolerate_known_test_failures": False}` returns 200 and `False`.
- GET returns `False`.
- A non-manager's PATCH returns 403. Reuse that test's viewer-client setup.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/projects/test_projects.py -q`.

**Commit:** `feat(projects): a setting to stop finishing on known failing tests (MC-97)`.

## Step 3: Let record_tests mark a run made on the start commit (on_base)

**Files:** `backend/app/workflow/records.py`, `backend/app/workflow/schemas.py`, `backend/app/mcp_server/workflow_tools.py`, `backend/tests/workflow/test_records.py`.

- `records.record_tests(..., on_base: Any = False)`. If it is not a bool, raise `_422("invalid_record")`. Store it on `WorkflowTestRun(on_base=...)`.
- `TestRunOut.on_base: bool = False`. `task_records` fills it with `on_base=t.on_base`.
- `_test_run_line`: `line = f"{_where_label(t)}: {'passed' if t.passed else 'FAILED'}{' on the start commit' if t.on_base else ''} — {t.command}"`.
- MCP `record_tests(..., failing: Any = None, on_base: Any = False)`. Pass it through. Add one sentence to the docstring: "`on_base`: true for a run on the commit the task branch started from (the finish stage's check)."

**Tests first** in `test_records.py`:
- `test_record_tests_on_base_is_stored_returned_and_marked`: from a finish run (`_building(db, tc, role="finish", step=None)`), call `record_tests` with `on_base=True` and `passed=False`, `failing=["test_a"]`.
  - The row has `on_base is True`.
  - `/records` returns `on_base: True`.
  - `records.test_runs_section([row])` contains `"FAILED on the start commit — uv run pytest"`.
  - A run without the flag stores `False`.
- Extend `test_record_tests_validation`: `on_base="yes"` gives `invalid_record`.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_records.py -q`.

**Commit:** `feat(workflow): record_tests marks a run on the start commit (MC-97)`.

## Step 4: Add failures to report_finish and the new report_test_failures tool

**Files:** `backend/app/workflow/finish.py`, `backend/app/mcp_server/workflow_tools.py`, new `backend/tests/workflow/test_finish_failures.py`, `backend/tests/mcp/test_workflow_tools.py`, `backend/tests/mcp/test_mcp.py`.

The validation helpers and `_store_failures` come from Appendix B; place them in finish.py. Then make these changes.

**`report_finish(db, run, outcome, branch, pr_url, tests_passed, back_merge_branch=None, back_merge_pr_url=None, failures=None, failing_total=None)`**
- Validate with `clean = _clean_failures(failures, required=False)` and `total = _clean_total(failing_total, len(clean))`.
- If `tests_passed is True` and (`clean` or `total is not None`), raise `invalid_finish_result`.
- Add `"failures": clean, "failing_total": total` to `run.step_result`. The `finish.reported` event data stays as it is.
- When `tests_passed` is true, set `wf.finish_tests = None`. Otherwise call `_store_failures(wf, clean, total, None, delivered=True)`.

**`async def report_test_failures(db, run, failures, diagnosis, failing_total=None) -> None`**
- Get the workflow and task with `wf, task = await build.lock_run_role(db, run, (RunRole.finish,))`.
- `clean = _clean_failures(failures, required=True)`, `total = _clean_total(...)`, `text = _clean_diagnosis(diagnosis)`.
- Set `run.step_result = {"test_failures": clean, "failing_total": total, "diagnosis": text}`. This replaces any earlier result of the same run, and a `report_finish` from the same run replaces it in turn.
- Call `_store_failures(wf, clean, total, text, delivered=False)`.
- Record no event here: the handler records one (step 6).

**MCP (`workflow_tools.py`)**
- `TOOL_ROLES["report_test_failures"] = frozenset({RunRole.finish})`. Add `"report_test_failures"` to `RUNNER_ONLY`.
- New tool: `report_test_failures(key: str, failures: Any, diagnosis: str, failing_total: Any = None) -> dict` returning `{"failures": len(...), "failing_total": failing_total}`. Docstring: "Report the failing tests a person must decide on, instead of delivering. `failures`: 1 to 20 {name (at most 300 characters), kind: new, base (also fails on the start commit) or flaky}; `diagnosis`: what failed and why (at most 2,000 characters); `failing_total` when more tests fail than you list. Then end your turn."
- `report_finish` gains `failures: Any = None, failing_total: Any = None`, passed through. Add to its docstring: "With tests_passed=false, `failures` lists the failing tests as for report_test_failures."

**Tests first.** Create `tests/workflow/test_finish_failures.py` and import helpers from `tests.workflow.test_review_done` (`_to_finish`, `_report`, `PR_URL`) and `tests.workflow.test_engine` (`_wf`, `_finish`, `_events`, `_runs`). Add these helpers:
```python
NEW = {"name": "e2e/a.spec.ts:3", "kind": "new"}
BASE = {"name": "e2e/mobile.spec.ts:98", "kind": "base"}
FLAKY = {"name": "e2e/freestyle.spec.ts:80", "kind": "flaky"}
async def _fail_report(run, failures, *, total=None): ...  # report_finish tests_passed=False with failures
async def _test_failures(run, failures, diagnosis="It fails because …", total=None): ...  # report_test_failures
```

Tests:
- `test_report_finish_stores_failures`: covers `wf.finish_tests` and `run.step_result["failures"]`. A later `report_finish(tests_passed=True)` clears `finish_tests`.
- `test_failures_validation`, each refused case giving a 422 with its code:
  - `invalid_finish_result`: `tests_passed=True` with failures; a kind of `"odd"`; a name that is not a str or is blank; failures that are not a list; `failing_total` below the list length, negative or a bool.
  - `too_large`: 21 entries; a 301-character name; a 2,001-character diagnosis.
  - For `report_test_failures`: `[]` and a blank diagnosis give `invalid_finish_result`.
- `test_report_test_failures_replaces_the_runs_result`: a second call overwrites `step_result`.

In `tests/mcp/test_workflow_tools.py`:
- Add to `ALL_WORKFLOW_TOOLS`: `"report_test_failures": {"failures": [{"name": "t", "kind": "new"}], "diagnosis": "d"}`.
- Add to `ALLOWED`: `"report_test_failures": {"finish"}`.
- Add it to the runner-only tuple near line 491 and to the connect-only loop near line 389.

In `tests/mcp/test_mcp.py`, add `"report_test_failures"` to the tool-name set.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_failures.py tests/mcp -q`.

**Commit:** `feat(workflow): finish runs report their failing tests (MC-97)`.

## Step 5: Freeze the setting when Done begins, add it to the finish prompt and extract _move_on

**Files:** `backend/app/workflow/engine.py`, `backend/app/workflow/finish.py`, `backend/tests/workflow/test_finish_failures.py`.

**engine.py**, next to `requires_human_review`:
```python
def tolerates_known(project: Project, wf: TaskWorkflow) -> bool:
    """MC-97: whether a finish goes on when its only failing tests are known ones (failing on the start commit, or
    flaky). Frozen when the Done stage began; a row from before falls back to the project's setting."""
    if wf.stage == Stage.done and wf.finish_tolerates_known is not None:
        return wf.finish_tolerates_known
    return project.tolerate_known_test_failures
```
In `enqueue`, for the finish role, build:
```python
project = await db.get(Project, task.project_id)
option = finishing_option(project, wf)
known = "tolerated" if tolerates_known(project, wf) else "not tolerated"
extra = [f"## Finishing\nFinishing option: {option.value}\n{delivery_lines(task)}\nKnown failing tests: {known}"]
```

**finish.py**
- In `enter_done`, add `wf.finish_tolerates_known = project.tolerate_known_test_failures` and `wf.finish_tests = None`. Add the setting to the existing "Frozen for the whole Done stage" comment.
- Extract the body of the `tests_passed is True` branch of `_handle_finish` (current lines 281–298) into `async def _move_on(db, wf, task) -> None` with the docstring "The finish is settled: wait for the pull request when its review or a back-merge requires it, else finished." The handler calls `await _move_on(db, wf, task)`. Behaviour is unchanged.

**Tests first** in `test_finish_failures.py`:
- `test_the_known_failures_line_is_in_the_finish_prompt`: the default project prompt contains `"Known failing tests: tolerated"`.
- `test_the_setting_is_frozen_when_done_begins`: patch `tolerate_known_test_failures=False` before the final review is approved. Then:
  - the prompt says `"not tolerated"`;
  - `wf.finish_tolerates_known is False`;
  - patching the project back to True during Done leaves `engine.tolerates_known(project, wf)` False.
- `test_a_row_from_before_falls_back_to_the_project`: a `TaskWorkflow(stage=Stage.done, finish_tolerates_known=None)` follows `Project(tolerate_known_test_failures=False)`. This is a pure unit test like `test_the_review_mode_is_frozen_at_done`.
- `test_enter_done_clears_finish_tests`: set `wf.finish_tests` while in Review, then check that Done begins with None.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_failures.py tests/workflow/test_review_done.py -q`.

**Commit:** `feat(workflow): freeze the known-failures setting when Done begins (MC-97)`.

## Step 6: Decide what happens when a finish run reports failing tests (_handle_finish)

**Files:** `backend/app/workflow/finish.py`, `backend/tests/workflow/test_finish_failures.py`, `backend/tests/workflow/test_review_done.py`.

Replace `_handle_finish` with the code in Appendix C: `_handle_finish`, `_settle_delivered`, `_needs_person`, `_covered`, `_answered_in_session`, `_raise_card` and `_accept_names`. It follows the design's table:
1. `tests_passed=true`: `_move_on`.
2. Failures delivered:
   - all known, the list complete and tolerated: event `finish.known_failures`, `settled="known"`, then `_move_on`;
   - covered by the card's accepted names: `settled="accepted"`, then `_move_on`;
   - the run resumed a finish session whose question a person answered: event `finish.failures_accepted` with `via="answer"` and that person as actor, the audit entry, then `_move_on`;
   - otherwise the card, delivered.
3. `report_test_failures`: the card, not delivered.
4. Neither: nudge, then `finish_incomplete` (unchanged).

`_raise_card` drops any earlier acceptance and records `finish.tests_failed` with `{failures, failing_total, delivered, start_branch}` before `engine.escalate(db, wf, "finish_tests_failed")`. No nudge happens on these paths.

**Tests first** in `test_finish_failures.py`, one per row (use `_finish(b.manager.id, run, "completed", session_id=...)` to end runs):
- `test_known_failures_finish_without_asking`: BASE and FLAKY with the default setting.
  - The workflow is `finished`.
  - `settled == "known"`.
  - The `finish.known_failures` event data has the failures and `start_branch`.
  - There is no escalation.
- `test_known_failures_wait_for_the_pr_when_review_is_required`: with `pr_review="human"`, the workflow waits on `human_code_review`.
- `test_setting_off_puts_known_failures_on_the_card`: gives `finish_tests_failed` with `delivered` True.
- `test_incomplete_list_is_never_tolerated`: BASE with `failing_total=25` gives the card.
- `test_new_failure_delivered_escalates_at_once`: the card, `finish.tests_failed` with `delivered` True, and one finish run only (no nudge).
- `test_report_test_failures_escalates_not_delivered`: the card, `delivered` False, and the stored diagnosis.
- `test_failing_report_without_names_escalates_card`.
- `test_answered_question_counts_as_acceptance`:
  - The finish run asks (`_ask`) and ends with `session_id="sess-f"`.
  - `_answer` resumes it.
  - The resumed run reports NEW and ends.
  - The workflow is finished; `finish.failures_accepted` has `actor_user_id == b.manager.id` and `via == "answer"`; there is an AuditLog `workflow.finish_failures_accepted`.
- `test_an_answer_in_another_session_does_not_count`: a question answered in session A; a later finish run with `resume_session_ref=None` reports NEW. The card follows.
- `test_no_report_still_nudges_then_finish_incomplete`.

In `test_review_done.py`:
- Rewrite `test_finish_without_report_or_failing_tests_nudged_then_escalated`: no report leads to a nudge; the nudge ends without a report and gives `finish_incomplete`.
- Rename it `test_finish_without_report_nudged_then_escalated`.
- Rewrite `test_resume_after_a_failing_finish_report_runs_finish_again` as `test_a_failing_finish_report_shows_the_card_and_pause_resume_returns_to_it`: a report with `tests_passed=False` gives `finish_tests_failed`; pause and resume give back `waiting_human`/`escalation` and the same reason, with no new run.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_failures.py tests/workflow/test_review_done.py -q`.

**Commit:** `feat(workflow): known failing tests finish, others raise finish_tests_failed (MC-97)`.

## Step 7: Add Finish anyway and Retry to the finish_tests_failed card

**Files:** `backend/app/workflow/finish.py`, `backend/app/workflow/engine.py`, `backend/app/workflow/context.py`, `backend/tests/workflow/test_finish_failures.py`.

- Add `_accept_tests_failed` and `_retry_tests_failed` from Appendix D, and register them:
  ```python
  engine.ACCEPT_HANDLERS["finish_tests_failed"] = _accept_tests_failed
  engine.RETRY_HANDLERS["finish_tests_failed"] = _retry_tests_failed
  ```
- In `context.resume_text`, add the kind `"failures_accepted"` from Appendix D, and add it to the docstring's payload list.
- engine.py:
  - `RESUME_HEADING["failures_accepted"] = "Failing tests accepted"`.
  - In `_pending_need`, change the condition to `((reported or {}).get("tests_passed") is True or (wf.finish_tests or {}).get("settled")) and requires_human_review(project, wf)`, and update its comment: a settled finish counts like passing tests.
  - Rewrite the comment above `ACCEPT_HANDLERS`: "reason -> what `accept` does. Registered by the stages that offer it (build, finish, git); any other reason gets 422 cannot_accept_here."
- Update the finish.py module docstring's Done section to the new table:
  - reported with passing tests, or known failures tolerated, or covered by an acceptance: move on;
  - otherwise `finish_tests_failed` (accept: Finish anyway; retry: a fresh finish);
  - report_test_failures: `finish_tests_failed`, not delivered;
  - no report: one nudge, then `finish_incomplete`.

**Tests first:**
- `test_finish_anyway_after_a_delivery_finishes`: accept through `POST /api/tasks/{key}/workflow/escalation {"action":"accept"}`. Then:
  - the workflow is `finished`;
  - `finish_tests.accepted_by` is the manager and `accepted` holds the names;
  - `settled` is `"accepted"`;
  - the `finish.failures_accepted` event has `via` `card`;
  - the audit entry exists.
- `test_finish_anyway_with_required_review_waits_for_the_pr`: then pause and resume give `human_code_review` and no new run.
- `test_finish_anyway_not_delivered_resumes_the_session`:
  - `report_test_failures`, ending with `session_id="sess-t"`, then accept.
  - The new finish run has `resume_session_ref == "sess-t"`.
  - Its `resume_prompt` contains the person's name, `<untrusted source="accepted_tests">` and the test name.
  - It reports `report_finish(tests_passed=False, failures=[NEW])` and ends; the workflow is finished.
- `test_a_test_outside_the_accepted_names_brings_the_card_back`: the resumed run reports NEW plus another new test. The card comes back, and `accepted_by` is cleared.
- `test_finish_anyway_without_a_session_goes_into_a_fresh_prompt`: no session id, so the prompt ends with `## Failing tests accepted` and the text.
- `test_retry_clears_and_starts_a_fresh_finish`: `finish_tests is None`, a new finish run with `resume_session_ref None`, and `nudged` False.
- `test_accept_handlers_include_finish_tests_failed`.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_failures.py tests/workflow/test_review_done.py tests/workflow/test_engine.py -q`.

**Commit:** `feat(workflow): Finish anyway and Retry on the finish_tests_failed card (MC-97)`.

## Step 8: Return finish_tests in the workflow API

**Files:** `backend/app/workflow/schemas.py`, `backend/app/workflow/router.py`, `backend/tests/workflow/test_finish_failures.py`.

```python
class FinishFailureOut(BaseModel):
    name: str
    kind: Literal["new", "base", "flaky"]

class FinishTestsOut(BaseModel):
    """MC-97: the finish run's failing tests, as it reported them, and how the finish settled."""
    failures: list[FinishFailureOut] = []
    failing_total: int | None = None
    diagnosis: str | None = None
    delivered: bool = False
    settled: Literal["known", "accepted"] | None = None
    accepted_by: str | None = None  # the person's name
```

- Add `WorkflowOut.finish_tests: FinishTestsOut | None = None`.
- In `router.workflow_out`, build it from `wf.finish_tests` when it is set. Resolve `accepted_by` with `(await db.get(User, uuid.UUID(ft["accepted_by"]))).name` when present; use None when the user is gone.

**Test first:** `test_workflow_api_returns_finish_tests`:
- After `report_test_failures`, GET `/api/tasks/{key}/workflow` returns `finish_tests` with failures, diagnosis, `delivered` False, `settled` None and `accepted_by` None.
- After accepting and finishing, it returns `settled` `"accepted"` and `accepted_by == b.manager.name`.
- A workflow without failures returns `finish_tests` None.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_finish_failures.py -q`.

**Commit:** `feat(workflow): the workflow API returns the finish's failing tests (MC-97)`.

## Step 9: Rewrite the finish methodology text and the finish run's next line

**Files:** `backend/app/workflow/methodology_texts/defaults/finish.md`, `backend/app/workflow/methodology_history.py`, `backend/app/mcp_server/workflow_tools.py`, `backend/app/workflow/finish.py`, `backend/tests/workflow/test_methodology.py`, `backend/tests/workflow/test_review_done.py`.

- Apply Appendix A to `finish.md`. Every listed section changes as shown; the rest stays word for word.
- Run `sha256sum app/workflow/methodology_texts/defaults/finish.md` and append the hash to `DEFAULT_HISTORY["finish"]`.
- `RUN_NEXT[RunRole.finish] = "Re-verify the tests (sort any failures), then perform the finishing option ({option}) and call report_finish, or call report_test_failures when a failure needs a person."`
- `FINISH_NUDGE = "Re-verify the tests, perform the finishing option, then call report_finish (or report_test_failures when a failing test needs a person)."` Update the assertion in `test_review_done.py` that checks the nudge ending.

**Tests first** in `test_methodology.py`: `test_finish_text_sorts_failing_tests`. The default finish body contains `report_test_failures`, `on_base=true`, `git switch --detach`, `Known failing tests`, `flaky` and `Finish anyway`, and no longer contains "If anything fails, **stop**". `test_default_history_ends_with_the_current_texts` must pass once the hash is appended.

**Run:** `megoocolab-runner services run test -- uv run pytest tests/workflow/test_methodology.py tests/workflow/test_review_done.py tests/mcp -q`.

**Commit:** `feat(workflow): the finish agent sorts failing tests and reports them (MC-97)`.

## Step 10: Regenerate the API types and add the failure texts to workflow.ts

**Files:** `frontend/src/lib/api-types.ts`, `frontend/src/lib/workflow.ts`, `frontend/src/lib/__tests__/workflow.test.ts`, plus any fixtures that tsc flags (`src/components/project/__tests__/fixture.ts`, `WorkflowSettings.test.tsx`).

Run `npm run gen:api` from `frontend/`. Then implement Appendix E in `workflow.ts`:
- `ESCALATION_REASON_TEXT.finish_tests_failed = "Tests failed at finish."`
- `"finish_tests_failed"` appended to `ACCEPTABLE_REASONS`
- `FinishTests`, `FailureKind`, `failureKindLabel`, `finishTestsSummary`, `finishedWithSummary`, `TOLERATE_KNOWN_HELP`
- `testRunText` appends ` (on the start commit)` when `run.on_base`

**Tests first** in `workflow.test.ts`:
- `finishTestsSummary`:
  - 1 new, 1 base, 1 flaky on develop gives `"Tests failed at finish: 3 failing (1 new, 1 also fails on develop, 1 flaky)"`;
  - only 1 new gives `"Tests failed at finish: 1 failing (1 new)"`;
  - no names gives `"The agent reported that the tests did not pass."`;
  - 20 names with `failing_total` 25 gives `"Tests failed at finish: 25 failing (20 new, 5 not listed)"`;
  - a null start branch gives "also fails on the start branch".
- `finishedWithSummary`:
  - known with 1 base and 1 flaky gives `"Finished with 2 known failing tests: 1 also fails on develop, 1 flaky"`;
  - known with 1 gives `"Finished with 1 known failing test: 1 flaky"`;
  - accepted gives `"Finished with 3 failing tests accepted by Ann"`, and with no names `"Finished with failing tests accepted by Ann"`.
- `testRunText` with `on_base: true` gives `"✗ 1 failed: a — uv run pytest (on the start commit)"`.

**Run:** `npx vitest run src/lib/__tests__/workflow.test.ts`, then `npx tsc --noEmit`.

**Commit:** `feat(workflow): texts for failing tests at finish (MC-97)`.

## Step 11: Show the failures on the escalation card and in the workflow panel

**Files:** new `frontend/src/components/workflow/FinishFailures.tsx`, `EscalationActions.tsx`, `WorkflowPanel.tsx`, new `__tests__/FinishFailures.test.tsx` and `__tests__/EscalationActions.test.tsx`, and `__tests__/WorkflowPanel.test.tsx`.

Implement Appendix F.

**Tests first.**

`FinishFailures.test.tsx`:
- It renders the summary, one list item per failure with its tag ("new", "also fails on develop", "flaky"), "and 5 more", the diagnosis as plain text (a `<b>x</b>` diagnosis shows literally), and the run lines from `testRunText`.
- When settled, it renders the `finishedWithSummary` line.

`EscalationActions.test.tsx`:
- For `finish_tests_failed` with `delivered` true: the summary, buttons Retry, "Finish anyway" and Pause, and the hint "Finish anyway records that you accepted these tests and finishes the task."
- With `delivered` false, the other hint.
- Clicking "Finish anyway" calls `onDecide("accept")`.
- `review_rounds_exhausted` still shows "Accept".
- `finish_tests_failed` without `finish_tests` shows the reason text and "Finish anyway".

`WorkflowPanel.test.tsx`:
- A finished workflow with `finish_tests.settled = "known"` shows "Finished with 2 known failing tests: …".
- A Done-stage test run returned by `/records` appears in the card's runs.

**Run:** `npx vitest run src/components/workflow`, then tsc, eslint on the changed files, and `npm test`.

**Commit:** `feat(workflow): the Tests failed at finish card with Finish anyway (MC-97)`.

## Step 12: Add activity texts for the new events and the setting in Workflow settings

**Files:** `frontend/src/components/task/ActivityThread.tsx`, `src/components/task/__tests__/ActivityThread.test.tsx`, `frontend/src/components/project/WorkflowSettings.tsx`, `src/components/project/__tests__/WorkflowSettings.test.tsx`.

**ActivityThread**, in `describeWorkflowEvent`. Import `finishTestsSummary` and `finishedWithSummary` from `@/lib/workflow`, and cast `data.failures` to `FinishTests["failures"]`.
- `finish.tests_failed`: `finishTestsSummary({failures, failing_total}, str(data.start_branch) ?? null)`.
- `finish.known_failures`: `finishedWithSummary({failures, settled: "known"}, start_branch)`.
- `finish.failures_accepted`: `accepted ${n} failing test${n===1?"":"s"}: ${first 5 names joined ", "}${more ? ` and ${more} more` : ""}`. With no names: `"accepted the failing tests"`. Append ` (by answering the agent's question)` when `via === "answer"`.
- Add `finish.tests_failed` and `finish.known_failures` to `STANDALONE`. `finish.failures_accepted` keeps the actor in front.

**WorkflowSettings**
- Add `const TOLERATE_KNOWN_LABEL = "Finish when the only failing tests are known ones";`.
- Add `tolerate_known_test_failures` to the form state.
- In the read-only view, add a block like the send-back one: `yesNo(...)` and `TOLERATE_KNOWN_HELP`.
- In the form, add a checkbox after the send-back one with the label and the help. The PATCH body includes the field; check how the existing save builds its body.

**Tests first:**
- ActivityThread: the three texts. The "answer" variant reads `"Ann accepted 2 failing tests: a, b (by answering the agent's question)"`, or whatever the actor prefix renders as in the existing tests.
- WorkflowSettings:
  - the read-only view shows the label with "On";
  - unticking the checkbox and saving sends `tolerate_known_test_failures: false`.

**Run:** `npx vitest run src/components/task src/components/project`, then tsc, eslint on the changed files, and `npm test`.

**Commit:** `feat(workflow): activity texts and project setting for known failing tests (MC-97)`.

## Step 13: Cover the card and Finish anyway in the end-to-end workflow test

**Files:** `frontend/e2e/workflow.spec.ts`.

Read `e2e/helpers/runner.ts` first to see how `onPrompt` matches. In this spec, every matching branch runs, and a resumed session's prompt is only its resume text.

**Scenario**
- Add `const ACCEPTED = "chose Finish anyway";` (it appears in the resume text from Appendix D) and `const FAILING = { name: "greeting.test:1", kind: "new" };`.
- Replace the `FINISH` branch with:
  ```ts
  onPrompt(
    FINISH,
    mcp("record_tests", { key: KEY, command: "make test", passed: false, failed: 1, failing: [FAILING.name] }),
    mcp("report_test_failures", { key: KEY, failures: [FAILING], diagnosis: "The greeting test expects a farewell." }),
  ),
  onPrompt(
    ACCEPTED,
    mcp("report_finish", { key: KEY, outcome: "pr_opened", branch: BRANCH, pr_url: PR_URL, tests_passed: false, failures: [FAILING] }),
  ),
  ```
- If the resumed prompt also contains `FINISH` (when there is no session), nest `ACCEPTED` and the plain report so that each run makes exactly one report.

**Section 9**
- Before the Done card appears, wait for `panel.getByText("Tests failed at finish: 1 failing (1 new)")`, with a 60 s timeout.
- Check that `panel.getByText(FAILING.name)` and the diagnosis are visible.
- Click `panel.getByRole("button", { name: "Finish anyway" })`.
- Then the existing Done assertions run, plus `panel.getByText(`Finished with 1 failing test accepted by ${ADMIN.name}`)`.
- The expected run list ends with `"finish completed", "finish completed"`.
- Check `reportFor(reports, ACCEPTED)`: its `session_events` resume the first finish session, as the existing fix check does.

**Run:** from `frontend/`, `megoocolab-runner services run e2e -- npx playwright test e2e/workflow.spec.ts --reporter=line`, then the full `megoocolab-runner services run e2e -- npx playwright test --reporter=line`. Report any failure that is not related to this change with its spec name. Don't fix it here.

**Commit:** `test(e2e): the finish card and Finish anyway in the workflow test (MC-97)`.

---

## Appendix A — `finish.md` changes

**Tools section.** Replace the `report_finish`, `ask_human` and `record_tests` bullets with:

```
- `report_finish(key, outcome, branch, pr_url?, tests_passed, back_merge_branch?, back_merge_pr_url?, failures?,
  failing_total?)`
  - `outcome` is `merged_local`, `pr_opened` or `branch_kept`.
  - `branch` is the branch name the work is on (or was merged from).
  - `pr_url` is the pull or merge request URL; required for `pr_opened`.
  - `tests_passed` is true only if your last full run in this session passed and you recorded it.
  - `failures` and `failing_total`: with `tests_passed=false`, the failing tests as in "Step 1".
  - `back_merge_branch` and `back_merge_pr_url`: only when your prompt names a "Back-merge into" branch and the
    option is not `keep_branch` (see "Back-merge"). The URL is required for `pr_opened`.
- `report_test_failures(key, failures, diagnosis, failing_total?)`: instead of delivering, when failing tests need a
  person (see "Step 1"). `failures` is 1 to 20 `{name, kind}`; `kind` is `new`, `base` or `flaky`; `diagnosis` is at
  most 2,000 characters. Then end your turn.
- `ask_human(key, question, choices?, mockup_html?, mockup_title?, mockup_choices?)`: when you are blocked by
  anything other than failing tests.
- `record_tests(key, command, passed, total?, failed?, skipped?, failing?, on_base?)`: record each verification run
  (see "Evidence before claims"). `on_base=true` for a run on the start commit.
```

**Step 1.** Replace the whole section, keeping the documents paragraph:

```
## Step 1: verify the tests

Before anything else, confirm the tree is clean (`git status`) and that you are on the task branch. A run that
stopped half-way may have left this worktree on the start commit: switch back to the task branch first. Commit
nothing from `.megoocolab/`.

(documents paragraph, unchanged)

Run the project's full test suite (and its linters or type checks) yourself, in this worktree, and record the run
with `record_tests`. If everything passes, go to Step 2.

If anything fails, do not change code. Sort every failing test into one kind:

1. **Flaky.** Run the failing tests again, together, up to two more times, and record each run. A test that passes
   in one of these runs is `flaky`.
2. **Already failing on the start branch.** For the tests that still fail, with a clean tree: find the commit the
   task branch started from (`git merge-base HEAD <start branch>`), run `git switch --detach <that commit>`, run
   only those tests, and record the run with `record_tests(..., on_base=true)`. Then switch back to the task branch
   and confirm `git status` is clean. A test that fails there too is `base`.
3. **New.** Every other failing test is `new`, including one you could not run on the start commit (for example
   because its dependencies differ there).

A failing linter, type check or build counts as one failing test, named after its command. Name each test as the
test runner prints it (at most 300 characters). List at most 20; when more fail, give the total as `failing_total`.

Then read the "Known failing tests" line in your prompt's "Finishing" section:

- **tolerated**, and every failure is `flaky` or `base`, and you listed them all: carry out the finishing option
  (Step 2). In the pull request description, add a "Known failing tests" section with two lists, "Already failing on
  <start branch>" and "Flaky (passed when run again)". Report with `tests_passed=false` and `failures`.
- Anything else (a `new` failure, more than 20 failures, or **not tolerated**): deliver nothing. Do not merge, push
  or open a pull request. Diagnose as "When something fails" says, call `report_test_failures` with the failures and
  your diagnosis, and end your turn. Do not use `ask_human` for failing tests.

### When a person chose "Finish anyway"

Your session may be resumed with a message saying a person accepted the failing tests you reported. Then carry out
the finishing option. In the pull request description, list those tests under "Known failing tests" as accepted by
that person, with their kinds. Report with `report_finish(..., tests_passed=false, failures=[...])` using the same
failures. The check in the first paragraph above still comes first.
```

**Step 2.**
- merge_local item 2, last sentence: "If they fail with a test that Step 1 did not sort as known, do not leave a broken merge behind: abort or reset your own merge, and call `report_test_failures` (that test is `new`)."
- merge_local item 4, and the report examples in pull_request and keep_branch: replace `tests_passed=true` with "`tests_passed` and `failures` as Step 1 found them".
- pull_request item 2: add the sentence "If the task branch already has an open pull request into the start branch (a retry after an earlier delivery), push to it and report its URL; do not open another."

**When something fails.** Replace the last paragraph with: "Then, for failing tests, call `report_test_failures` with the failures and a diagnosis: the failing command, what the output said, and the root cause you found (or what you ruled out). End your turn. For any other blocker, call `ask_human`."

**Evidence before claims**, point 3: use the new `record_tests` signature with `on_base?`.

**Hard rules.** Replace the last bullet with "Call `report_finish` at most once per run, and only after the option (and any back-merge) has actually been carried out."

**When you are blocked.** Use "Merge conflicts you cannot resolve safely, a missing CLI or login, a rejected push: call `ask_human` …". Then add: "Failing tests are not a blocker to ask about: use `report_test_failures`."

**When to end your turn:** "Right after `report_finish`, `report_test_failures` or `ask_human`. Never end a turn without one of them."

## Appendix B — finish.py validation and storage

```python
KINDS = ("new", "base", "flaky")
MAX_FAILURES = 20
MAX_FAILURE_NAME = 300
MAX_DIAGNOSIS = 2000


def _clean_failures(value, *, required: bool) -> list[dict]:
    """The agent's failing tests: [{name, kind}], at most 20; refused when malformed (invalid_finish_result) or
    oversize (too_large)."""
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise _422("invalid_finish_result")
    if len(value) > MAX_FAILURES:
        raise _422("too_large")
    out = []
    for entry in value:
        name = entry.get("name") if isinstance(entry, dict) else None
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if not isinstance(name, str) or kind not in KINDS:
            raise _422("invalid_finish_result")
        name = strip_nul(name).strip()
        if not name:
            raise _422("invalid_finish_result")
        if len(name) > MAX_FAILURE_NAME:
            raise _422("too_large")
        out.append({"name": name, "kind": kind})
    if required and not out:
        raise _422("invalid_finish_result")
    return out


def _clean_total(value, listed: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < listed:
        raise _422("invalid_finish_result")
    return value


def _clean_diagnosis(value) -> str:
    if not isinstance(value, str) or not strip_nul(value).strip():
        raise _422("invalid_finish_result")
    value = strip_nul(value).strip()
    if len(value) > MAX_DIAGNOSIS:
        raise _422("too_large")
    return value


def _store_failures(wf, failures, failing_total, diagnosis, *, delivered: bool) -> None:
    """A new report replaces the stored one. An acceptance is kept until the handler compares it (step 6)."""
    kept = {k: v for k, v in (wf.finish_tests or {}).items() if k in ("accepted_by", "accepted_at", "accepted")}
    wf.finish_tests = {"failures": failures, "failing_total": failing_total, "diagnosis": diagnosis,
                       "delivered": delivered, "settled": None, **kept}
```

`wf.finish_tests` is a plain JSONB column. Always assign a new dict; never mutate it in place.

## Appendix C — `_handle_finish` and its helpers

```python
async def _handle_finish(db, wf, task, run) -> None:
    if await _asked_or_answered(db, wf, task, run):
        return
    result = run.step_result or {}
    if result.get("tests_passed") is True:
        await _move_on(db, wf, task)
    elif "tests_passed" in result:  # delivered with failing tests
        await _settle_delivered(db, wf, task, run)
    elif "test_failures" in result:  # report_test_failures: nothing delivered
        await _raise_card(db, wf, task, delivered=False)
    elif not wf.nudged:
        ...  # unchanged nudge
    else:
        await engine.escalate(db, wf, "finish_incomplete")


def _needs_person(ft: dict, tolerated: bool) -> list[dict]:
    failures = ft.get("failures") or []
    complete = ft.get("failing_total") is None or ft["failing_total"] <= len(failures)
    if not tolerated or not complete:
        return failures
    return [f for f in failures if f["kind"] == "new"]


def _covered(ft: dict, tolerated: bool) -> bool:
    """Every failure that needs a person was accepted on the card in this Done round (no names: any acceptance)."""
    if not ft.get("accepted_by"):
        return False
    return {f["name"] for f in _needs_person(ft, tolerated)} <= set(ft.get("accepted") or [])


async def _settle_delivered(db, wf, task, run) -> None:
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    project = await db.get(Project, task.project_id)
    tolerated = engine.tolerates_known(project, wf)
    failures = ft.get("failures") or []
    if failures and not _needs_person(ft, tolerated):
        wf.finish_tests = {**ft, "settled": "known"}
        await engine.record_workflow_event(db, task, None, "finish.known_failures",
                                           {"failures": failures, "start_branch": task.start_branch})
    elif _covered(ft, tolerated):
        wf.finish_tests = {**ft, "settled": "accepted"}
    elif (answerer := await _answered_in_session(db, task, run)) is not None:
        await _accept_names(db, wf, task, answerer, via="answer", settled="accepted")
    else:
        await _raise_card(db, wf, task, delivered=True)
        return
    await _move_on(db, wf, task)


async def _answered_in_session(db, task, run) -> uuid.UUID | None:
    """The person who answered a question of the finish session this run resumed: their answer let it deliver."""
    if not run.resume_session_ref:
        return None
    return await db.scalar(
        select(WorkflowQuestion.answered_by)
        .join(AgentRun, AgentRun.id == WorkflowQuestion.run_id)
        .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.answered,
               AgentRun.workflow_role == RunRole.finish, AgentRun.session_ref == run.resume_session_ref)
        .order_by(WorkflowQuestion.answered_at.desc())
        .limit(1)
    )


async def _accept_names(db, wf, task, user_id, *, via: str, settled: str | None) -> None:
    """Record who accepted which failing tests: on the workflow, an event and an audit entry."""
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    names = [f["name"] for f in ft.get("failures") or []]
    wf.finish_tests = {**ft, "accepted_by": str(user_id), "accepted_at": datetime.now(UTC).isoformat(),
                       "accepted": names, "settled": settled}
    await engine.record_workflow_event(db, task, user_id, "finish.failures_accepted", {
        "failures": ft.get("failures") or [], "failing_total": ft.get("failing_total"), "via": via})
    await audit.record(db, "workflow.finish_failures_accepted", actor_id=user_id, target_type="task",
                       target_id=task.id, data={"names": names, "failing_total": ft.get("failing_total"), "via": via})


async def _raise_card(db, wf, task, *, delivered: bool) -> None:
    ft = {k: v for k, v in (wf.finish_tests or {"failures": []}).items()
          if k not in ("accepted_by", "accepted_at", "accepted")}
    wf.finish_tests = {**ft, "delivered": delivered, "settled": None}
    await engine.record_workflow_event(db, task, None, "finish.tests_failed", {
        "failures": ft.get("failures") or [], "failing_total": ft.get("failing_total"), "delivered": delivered,
        "start_branch": task.start_branch})
    await engine.escalate(db, wf, "finish_tests_failed")
```

Imports to add: `QuestionStatus`, `WorkflowQuestion` from `app.workflow.models`. `audit` and `AgentRun` are already imported.

## Appendix D — accept, retry and the resume text

```python
async def _accept_tests_failed(db, wf, task, user) -> None:
    """Escalation `accept` ("Finish anyway"): the person accepts the failing tests. Delivered: the finish moves on.
    Not delivered: the reporting session resumes to deliver and list them (a fresh prompt when it has no session)."""
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    delivered = ft.get("delivered", True)
    await _accept_names(db, wf, task, user.id, via="card", settled="accepted" if delivered else None)
    if delivered:
        await _move_on(db, wf, task)
        return
    wf.nudged = False
    last = await engine.latest_run(db, task.id)
    session = last.session_ref if last is not None and last.workflow_role == RunRole.finish else None
    await engine.enqueue(
        db, wf, task, RunRole.finish, resume_kind="failures_accepted", requested_by=user.id,
        payload={"by": user.name, "names": [f["name"] for f in ft.get("failures") or []],
                 "failing_total": ft.get("failing_total")},
        resume_session_ref=session,
    )


async def _retry_tests_failed(db, wf, task, user) -> None:
    """Escalation `retry`: forget the report and its acceptance, and run the finish again from the start."""
    wf.finish_tests = None
    await engine.enqueue(db, wf, task, RunRole.finish, requested_by=user.id)
```

`context.resume_text`:

```python
if kind == "failures_accepted":
    names = payload.get("names") or []
    more = (payload.get("failing_total") or 0) - len(names)
    listed = "\n".join(names) or "(you named no tests)"
    if more > 0:
        listed += f"\n…and {more} more"
    return _bounded(
        f"{payload.get('by') or 'A person'} chose Finish anyway: they accepted the failing tests you reported.\n",
        "accepted_tests", listed,
        "\nCarry out the finishing option now. In the pull request description, list these tests under \"Known "
        "failing tests\" as accepted by that person. Then call report_finish with tests_passed=false and the same "
        "failures.",
    )
```

## Appendix E — `workflow.ts` additions

```ts
export type FinishTests = NonNullable<Workflow["finish_tests"]>;
export type FailureKind = FinishTests["failures"][number]["kind"];

export function failureKindLabel(kind: FailureKind, startBranch: string | null): string {
  if (kind === "base") return `also fails on ${startBranch ?? "the start branch"}`;
  return kind; // "new" | "flaky"
}

const KIND_ORDER: FailureKind[] = ["new", "base", "flaky"];
function kindCounts(failures: FinishTests["failures"], startBranch: string | null): string[] {
  return KIND_ORDER.map((k) => [k, failures.filter((f) => f.kind === k).length] as const)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} ${failureKindLabel(k, startBranch)}`);
}

/** The card's first line: "Tests failed at finish: 3 failing (1 new, 1 also fails on develop, 1 flaky)". */
export function finishTestsSummary(t: Pick<FinishTests, "failures" | "failing_total">, startBranch: string | null): string {
  const failures = t.failures ?? [];
  if (!failures.length && !t.failing_total) return "The agent reported that the tests did not pass.";
  const total = Math.max(t.failing_total ?? 0, failures.length);
  const parts = kindCounts(failures, startBranch);
  if (total > failures.length) parts.push(`${total - failures.length} not listed`);
  return `Tests failed at finish: ${total} failing (${parts.join(", ")})`;
}

/** After the finish: "Finished with 2 known failing tests: …" or "Finished with 3 failing tests accepted by Ann". */
export function finishedWithSummary(t: Pick<FinishTests, "failures" | "failing_total" | "settled" | "accepted_by">, startBranch: string | null): string {
  const n = Math.max(t.failing_total ?? 0, t.failures?.length ?? 0);
  const tests = `${n} ${t.settled === "known" ? "known " : ""}failing test${n === 1 ? "" : "s"}`;
  if (t.settled === "known") return `Finished with ${tests}: ${kindCounts(t.failures, startBranch).join(", ")}`;
  return `Finished with ${n ? tests : "failing tests"} accepted by ${t.accepted_by ?? "a person"}`;
}

export const TOLERATE_KNOWN_HELP =
  "On: at finish, a test that also fails on the branch the task started from, or that passes when run again " +
  "(flaky), doesn't stop the task; the pull request lists it. Off: any failing test stops the finish and asks you.";
```

## Appendix F — `FinishFailures.tsx`, `EscalationActions`, `WorkflowPanel`

`FinishFailures({ tests, startBranch, runs = [] }: { tests: FinishTests; startBranch: string | null; runs?: TestRun[] })`:
- `<p>`: when `tests.settled` is set, `finishedWithSummary(tests, startBranch)`; otherwise `finishTestsSummary(tests, startBranch)`.
- When there are failures, `<ul aria-label="Failing tests" className="space-y-0.5 text-xs">`. Each `<li>` holds `<code className="break-all">{f.name}</code>` and a tag `<span className="ml-1 rounded border px-1 text-muted-foreground">{failureKindLabel(f.kind, startBranch)}</span>`. Add a last `<li>` "and N more" when `failing_total > failures.length`.
- When there is a diagnosis: `<p className="text-xs text-muted-foreground">Diagnosis</p><p className="whitespace-pre-wrap text-xs">{tests.diagnosis}</p>`. Render it as text only; never use dangerouslySetInnerHTML.
- When there are runs: `<details className="text-xs"><summary>Test runs at finish ({runs.length})</summary><ul>{runs.map((r) => <li key={r.id}>{testRunText(r)}</li>)}</ul></details>`.

`EscalationActions`:
- Add the prop `runs?: TestRun[]`. Set `const failed = wf.escalation_reason === "finish_tests_failed";`.
- When `failed && wf.finish_tests`, render `<FinishFailures tests={wf.finish_tests} startBranch={wf.start_branch ?? null} runs={runs} />` instead of the reason `<p>`. Otherwise render the `<p>` as before.
- The accept button's label is `"Mark merged"` for `merge_not_confirmed`, `"Finish anyway"` for `finish_tests_failed`, and `"Accept"` otherwise.
- When `failed && canDecide`, add `<p className="text-xs text-muted-foreground">`:
  - when `wf.finish_tests?.delivered === false`: "Finish anyway records that you accepted these tests; the agent then delivers the work and lists them in the pull request.";
  - otherwise: "Finish anyway records that you accepted these tests and finishes the task."
- Update the component's doc comment.

`WorkflowPanel`:
- `const doneRuns = (records.data?.test_runs ?? []).filter((r) => r.stage === "done");`
- Pass `runs={doneRuns}` to `EscalationActions`.
- After the escalation block, add `{!escalating && wf.finish_tests?.settled && <FinishFailures tests={wf.finish_tests} startBranch={wf.start_branch ?? null} runs={doneRuns} />}`.
- `ChatEscalation` is unchanged: chat rounds have no finish runs.

## Final verification

From `backend/`:
- `megoocolab-runner services run test -- uv run pytest -q -n auto`
- `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`

From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src/lib/workflow.ts src/components/workflow src/components/task/ActivityThread.tsx src/components/project/WorkflowSettings.tsx e2e/workflow.spec.ts`
- `npm test`
- `megoocolab-runner services run e2e -- npx playwright test --reporter=line`

Manual check on the dev stack: a task whose finish run reports a `new` failure shows "Tests failed at finish: 1 failing (1 new)" with Retry, Finish anyway and Pause. Finish anyway finishes the task, or waits for the pull request when its review is required. The workflow panel then reads "Finished with 1 failing test accepted by <name>".
