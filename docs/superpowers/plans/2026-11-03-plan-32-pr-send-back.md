# Changes requested on the PR send the task back — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** with a project checkbox on, a "changes requested" review or a `/fix` comment on the task's pull request
sends the task back to its agent. The agent fixes the code and pushes to the same branch, at most 3 rounds before
it asks the human.

**Architecture:**
- **Triggers:** piece 2's `activity.record` says when an entry is a trigger: a review whose verdict becomes
  `changes_requested`, or a comment starting with `/fix`. The new `app/git/send_back.py` decides on it under the
  workflow lock, then either enqueues a `pr_fix` run (stage shown as Build) or escalates on the fourth round.
- **The fix run:** a new run role `pr_fix`, with its own methodology text, prompt section and MCP tool
  `report_pr_fix`. When the run ends, the handler returns the workflow to waiting for the merge, or escalates.
- **The UI:** a project checkbox, the panel's sent-back line with "Don't send back", and Activity and escalation
  texts.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic, the workflow engine (`app/workflow`), the MCP server; Next.js 16,
React 19, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-pr-send-back-design.md`

## Global Constraints

- **Checkbox:**
  - the project field is `send_back_on_changes_requested`, a bool, default false (`server_default=false()`);
  - its label: "Send the task back when changes are requested on its pull request";
  - its help: "A 'changes requested' review, or a comment starting with /fix, sends the task back to its agent. The
    agent fixes the code and pushes to the same pull request. At most 3 rounds, then it asks you. On GitLab, use a
    /fix comment."
- **When a trigger counts:** the checkbox is on, the workflow is `status == waiting_human` and
  `needs == human_code_review`, and the trigger is about the workflow's own PR (`wf.pr_url`, trailing `/` ignored).
- **`/fix`:** an excerpt that, after leading spaces, starts with `/fix` (case-insensitive) followed by the end or
  whitespace.
- **GitHub permission:** only `author_association` in `OWNER`, `MEMBER` or `COLLABORATOR`. GitLab and Gitea carry
  none, so any author counts.
- **Rounds:** `MAX_PR_FIX_ROUNDS = 3` per pull request. A trigger beyond that escalates `pr_fix_rounds_exhausted`.
- **Escalation reasons and texts:**
  - `pr_fix_rounds_exhausted`: "Changes were requested again after 3 fix rounds."
  - `pr_fix_incomplete`: "The fix run ended without pushing a fix with passing tests."
  - Accept on either returns the workflow to waiting for the merge.
- **Activity texts:**
  - `pr.sent_back`: "Sent back to its agent: changes requested on PR #n by {who} (round r of 3)", or
    "Sent back to its agent: /fix on PR #n by {who} (round r of 3)";
  - `pr.fix_pushed`: "Fixed and pushed to PR #n (round r of 3)", with the agent's summary under it;
  - `pr.send_back_cancelled`: "{user} stopped the fix: back to waiting for the merge".
- **Panel line:** "Changes requested on PR #n by {who} · {agent} is fixing them · round r of 3", with the button
  "Don't send back".
- **Never:** a send-back from a push, from an event during a fix, or from a finished task. No new PR, no force-push.
- **Rules from earlier pieces:**
  - migrations only against `megoo_migrate`;
  - never two pytest runs at once;
  - ruff from `backend/`;
  - commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - regenerate `src/lib/api-types.ts` with `SECRET_KEY=... npm run gen:api`, then delete `openapi.json`.

## Review Focus

1. **A changes-requested review arriving after its line comments,** whose entry was first folded as `commented`:
   it sends back once when the verdict turns to `changes_requested`. Later line comments of the same review don't
   send back again. Pinned in Task 2 by `test_a_review_sends_back_once_whichever_part_arrives_first`.
2. **A trigger about another pull request of the same task** (a back-merge PR, or an older PR): it does nothing.
   Pinned in Task 2 by `test_a_trigger_about_another_pr_does_nothing`.
3. **"Don't send back" while the fix run is still running:** the cancelled run must not be counted as a failure and
   rerun. The workflow waits for the merge. Pinned in Task 4 by `test_dont_send_back_cancels_without_a_rerun`.
4. **A new pull request reported after rounds were used:** the count starts again. Pinned in Task 2 by
   `test_rounds_start_again_for_a_new_pr`.
5. **The webhook commits, then dispatches the queued fix run.** A trigger must start a run without waiting for
   another event. Pinned in Task 2 by `test_a_trigger_dispatches_the_fix_run`, which asserts
   `engine.dispatch_queued` is called after the delivery's commit.

---

### Task 1: The project checkbox and the workflow's fix state

**Files:**
- Modify: `backend/app/projects/models.py` (field), `projects/schemas.py` (`ProjectPatch`, `ProjectOut`),
  `projects/router.py` (PATCH applies it), `projects/service.py` (`project_out`).
- Modify: `backend/app/workflow/models.py`. Add to `TaskWorkflow`:
  - `pr_fix_rounds: int` (default 0, `server_default="0"`);
  - `pr_fix_pr_url: Text|None`: the PR the count belongs to;
  - `pr_fix_trigger: JSONB|None`: `{kind: "review"|"fix_comment", by, pr_number, excerpt, where}`.
- Create: an Alembic migration, autogenerated on `megoo_migrate`.
- Modify: `backend/app/workflow/schemas.py` (`TaskWorkflowOut` gains `pr_fix_rounds` and `pr_fix_trigger`) and
  where it's built.
- Modify: `frontend/src/components/project/WorkflowSettings.tsx`, `frontend/src/lib/workflow.ts` (`SEND_BACK_HELP`),
  and the regenerated `api-types.ts`.
- Test: `backend/tests/projects/` (the test file holding `require_human_code_review` PATCH tests),
  `frontend/src/components/project/__tests__/WorkflowSettings.test.tsx` and its fixture.

- [ ] **Step 1: Write the failing tests:**
  - `test_send_back_setting_defaults_off_and_patches`: a new project reads `False`, a PATCH to `True` reads back, and
    only managers may change it, as for `require_human_code_review`.
  - vitest `"the send-back checkbox saves and explains itself"`: the checkbox with the exact label and help, and the
    PATCH body containing `send_back_on_changes_requested: true`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Generate and apply the migration, then regenerate the API types.
- [ ] **Step 4: Run** `tests/projects` and the WorkflowSettings vitest, then `npx tsc --noEmit`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(projects): a checkbox to send the task back when changes are requested on its PR`.

### Task 2: Triggers send the task back

**Files:**
- Modify: `backend/app/git/events.py`. GitHub comment, review and review-comment data gain
  `association: str|None`, from `comment.author_association` and `review.author_association`.
- Modify: `backend/app/git/activity.py`:
  - `record` collects triggers and returns them alongside the count; `_fold_review` reports when a verdict becomes
    `changes_requested`;
  - after each trigger it calls `send_back.consider` (in the same savepoint).
- Create: `backend/app/git/send_back.py`.
- Modify: `backend/app/git/router.py`. `_handle` commits, then calls `engine.dispatch_queued(db)` when the record
  queued a run.
- Test: `backend/tests/git/test_send_back.py`.

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Trigger:
      kind: str             # "review" | "fix_comment"
      pr_url: str | None
      pr_number: int | None
      by: str               # the actor's name (agent or person)
      excerpt: str
      where: str | None     # "src/a.py:88" from the review's first line comment, when known
      association: str | None
      host: str             # GitKind value

  MAX_PR_FIX_ROUNDS = 3
  def is_fix_comment(text: str) -> bool
  async def consider(db: AsyncSession, task: Task, trigger: Trigger) -> str
      # "sent_back" | "exhausted" | "ignored:<why>"
  ```
- **`consider`:**
  1. Lock with `engine.lock_task(db, task)`.
  2. Check the Global Constraints: setting, state, same PR, and the GitHub association. If any fails, return
     `ignored:<why>`.
  3. When `wf.pr_fix_pr_url` differs from `wf.pr_url`, reset `pr_fix_rounds = 0` and set `pr_fix_pr_url`.
  4. If `pr_fix_rounds >= 3`, store the trigger, escalate `pr_fix_rounds_exhausted` and return `"exhausted"`.
  5. Otherwise:
     - `pr_fix_rounds += 1`, and store the trigger;
     - record `pr.sent_back` `{pr_url, pr_number, by, kind, excerpt, where, round, of: 3}`;
     - `engine.set_stage(db, wf, task, Stage.build)`;
     - `wf.status = running`, `wf.needs = None`;
     - `engine.enqueue(db, wf, task, RunRole.pr_fix, requested_by=<agent owner id>)`.
  - Task 3 adds `RunRole.pr_fix`. Until then, this task's tests patch `engine.enqueue` to record the call.
  - **Ruling allowed:** if Task 3's role must exist first, do Task 3's model part, `RunRole.pr_fix`, here and ledger
    it.

- [ ] **Step 1: Write the failing tests.** They go through the webhook, with `_world` as in
  `tests/git/test_activity.py`, a `TaskWorkflow` waiting with `needs=human_code_review` and `pr_url` set, and the
  checkbox on:
  - `test_changes_requested_sends_the_task_back`: one `pr.sent_back` with `round == 1`, stage `build`, status
    `running`, one queued `pr_fix` run, and `wf.pr_fix_trigger.by == "rev"`.
  - `test_fix_comment_sends_back_and_other_comments_dont`: `/fix add a delay` sends back. These don't:
    `"please /fix"`, `"/fixed it"`, `"LGTM"`.
  - `test_nothing_without_the_checkbox_or_outside_waiting`: the checkbox off; the workflow `running`; the workflow
    `finished`.
  - `test_github_needs_write_access`: `author_association` `NONE` and `CONTRIBUTOR` are ignored; `COLLABORATOR` sends
    back. A GitLab `/fix` note with no association sends back.
  - `test_a_review_sends_back_once_whichever_part_arrives_first`: line comment, then review `changes_requested`,
    then another line comment gives exactly one `pr.sent_back`.
  - `test_a_trigger_about_another_pr_does_nothing`.
  - `test_the_fourth_trigger_escalates`: three send-backs, each followed by setting the workflow back to waiting,
    then a fourth gives `escalation_reason == "pr_fix_rounds_exhausted"` and no fourth run.
  - `test_rounds_start_again_for_a_new_pr`.
  - `test_a_trigger_dispatches_the_fix_run`.
- [ ] **Step 2: Run** `uv run pytest -q tests/git/test_send_back.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/git`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): changes requested or /fix on the PR sends the task back to its agent`.

### Task 3: The fix run

**Files:**
- Modify: `backend/app/workflow/models.py` (`RunRole.pr_fix`).
- Modify: `backend/app/workflow/engine.py`:
  - `ROLE_POLICY[pr_fix] = workspace`;
  - add `pr_fix` to `FRESH_ROLES`;
  - `ACCEPT_HANDLERS` for both new reasons: `set_stage(done)` and `wait_for(human_code_review)`.
- Modify: `backend/app/workflow/context.py`:
  - `ROLE_KEY[pr_fix] = "pr_fix"`;
  - a prompt section for `pr_fix`, from `wf.pr_url`, `wf.branch` and `wf.pr_fix_trigger`:

    ```
    ## Changes requested on the pull request
    Pull request: <url> (branch <branch>) · round r of 3
    <who> asked: "<excerpt>" [at <where>]
    ```
- Modify: `backend/app/workflow/methodology.py` (`KEYS[Stage.done]` gains `"pr_fix"`).
- Create: `backend/app/workflow/methodology_texts/defaults/pr_fix.md`. Its heading is
  `# Fix: address the changes requested on the pull request`. It says:
  - read every review and comment with the host CLI (`gh pr view <url> --comments`, `glab mr view <n> --comments`,
    `tea pulls <n>`);
  - fix only what was asked;
  - run the tests;
  - commit and `git push` to the same branch: never force-push, never open a new pull request, never change branches;
  - call `report_pr_fix(key, summary, tests_passed)`.
- Modify: `backend/app/mcp_server/workflow_tools.py`:
  - add `report_pr_fix` to `TOOL_ROLES`;
  - add `RUN_NEXT[pr_fix] = "Fix what was asked on the pull request, run the tests, push to the same branch, then
    call report_pr_fix."`;
  - add `pr_fix` to the roles of `ask_human`, `record_decision` and `record_tests`;
  - add `report_pr_fix` to `RUNNER_ONLY`;
  - add the tool, which stores `{summary, tests_passed}` in `run.step_result` through a
    `send_back.report_fix(db, run, summary, tests_passed)`.
- Modify: `backend/app/git/send_back.py`. Add `_handle_pr_fix(db, wf, task, run)`, registered in
  `engine.ROLE_HANDLERS`:
  - after an answered question (as `_handle_finish`);
  - when `tests_passed` is true: `set_stage(done)`, record `pr.fix_pushed` `{pr_url, pr_number, round, of: 3,
    summary}`, then `wait_for(human_code_review)` and `git.settle_done`;
  - otherwise one nudge, then escalate `pr_fix_incomplete`.
- Test: `backend/tests/git/test_send_back.py`, `backend/tests/workflow/` (the methodology key list test, if one
  pins the keys).

- [ ] **Step 1: Write the failing tests:**
  - `test_fix_run_prompt_names_the_pr_and_the_request`: the prompt holds the `## Changes requested on the pull
    request` section, the PR URL, the branch, "round 1 of 3" and the excerpt, plus the methodology heading.
  - `test_fix_reported_with_passing_tests_waits_for_the_merge_again`: `report_pr_fix` through the MCP tool, then the
    run ends. That gives stage `done`, `needs == human_code_review`, and one `pr.fix_pushed` with the summary.
  - `test_fix_without_a_report_nudges_then_escalates`: `escalation_reason == "pr_fix_incomplete"` after the nudge run
    also ends without one.
  - `test_accept_returns_to_waiting_for_the_merge` for both reasons.
  - `test_report_pr_fix_only_in_a_fix_run`: the tool is refused in a finish run with `not_allowed_in_role`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** In Task 2's tests, swap the patched `enqueue` for the real run where it was patched.
- [ ] **Step 4: Run** `tests/git tests/workflow tests/mcp_server`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workflow): the fix run pushes to the same pull request and reports`.

### Task 4: "Don't send back", and the words in the UI

**Files:**
- Modify: `backend/app/workflow/router.py` and `backend/app/git/send_back.py`. Add
  `POST /api/tasks/{key}/workflow/send-back/cancel`, for those who can act on the workflow (`can_act`). It:
  - requires a live `pr_fix` run, else 409 `no_fix_running`;
  - sets `set_stage(done)` and `wait_for(human_code_review)` **before** cancelling the run, so the run-ending path
    sees no running workflow and doesn't count a failure;
  - records `pr.send_back_cancelled`;
  - cancels the run through `agent_runs.service.cancel_run`.
- Modify: `frontend/src/lib/workflow.ts`. Add the escalation texts, and `ACCEPTABLE_REASONS` gains both reasons.
- Modify: `frontend/src/components/task/ActivityThread.tsx` (`describeWorkflowEvent`): the three `pr.*` texts, with
  `pr.fix_pushed`'s summary as a muted line, plain text. `pr.*` events are `STANDALONE` with no lead, except
  `pr.send_back_cancelled`, led by the user.
- Modify: `frontend/src/components/workflow/WorkflowPanel.tsx`. While the workflow is running a `pr_fix` round (stage
  `build` with `pr_fix_trigger` set and status `running`), it shows the panel line and the "Don't send back" button.
  The button confirms, then POSTs.
- Test:
  - backend `tests/git/test_send_back.py`: `test_dont_send_back_cancels_without_a_rerun`,
    `test_dont_send_back_needs_a_fix_running`;
  - frontend `WorkflowPanel.test.tsx` and `ActivityThread.test.tsx`: the exact texts and the button's POST;
  - `workflow.test.ts`: the escalation texts.

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/git tests/workflow` and `npx vitest run`, `npx tsc --noEmit`, `npx eslint src`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(workflow): see a send-back on the task, and stop it`.

### Task 5: End to end

**Files:**
- Modify: `frontend/e2e/git.spec.ts`:
  - turn the project's checkbox on with the step-2 PATCH, alongside `require_human_code_review`;
  - add an `onPrompt("# Fix: address the changes requested on the pull request", write, commit,
    mcp("report_pr_fix", {key, summary: "Added a back-off", tests_passed: true}))` to `workflowFor`;
  - the existing changes-requested review gains `author_association: "COLLABORATOR"`. Then expect, in this order:
    - Activity shows "Sent back to its agent: changes requested on PR #1 by rev (round 1 of 3)";
    - the fix run ends;
    - Activity shows "Fixed and pushed to PR #1 (round 1 of 3)" and "Added a back-off";
    - the panel's "Mark merged" is visible again (waiting for the merge).
  - The existing merge step then finishes the task as before.

- [ ] **Step 1: Write the e2e steps.**
- [ ] **Step 2: Run** the git spec on a fresh megoo-e2e stack. Expected: PASS.
- [ ] **Step 3: Run** the full backend suite (alone), the web suite, tsc and eslint, and the whole e2e suite.
  Expected: all green.
- [ ] **Step 4: Commit** `test(e2e): changes requested on the PR send the task back and the agent fixes it`.
