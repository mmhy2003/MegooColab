# Pull request review: None, Human or Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a project chooses who reviews its pull requests: None, Human or Agent. With Agent, a review run posts its
review on the host from the owner's account, merges when it approves, and sends the task back when it asks for
changes.

**Architecture:**
- `Project.pr_review` (`none|human|agent`) and `pr_reviewer_agent_id` replace `require_human_code_review`, and the
  org default follows. `engine.requires_human_review` means "waits on its PR" (not none).
- A new read-only, fresh run role `pr_review` with its methodology text, a prompt section, and the MCP tool
  `submit_pr_review`.
- With Agent, `app/git/agent_review.py` starts the review run after Finish and after each pushed fix, and handles
  its end:
  - merged → wait for the merge and settle;
  - not merged → escalate;
  - changes → piece 3's send-back core;
  - nothing reported → nudge, then escalate.
- Webhook copies carrying the marker are skipped. The UI shows the setting, the panel line, Activity and the
  escalations.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic, the workflow engine, the MCP server; Next.js 16, React 19,
vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-agent-pr-review-design.md`

## Global Constraints

- **Setting values:** `pr_review` is one of `none`, `human`, `agent` (String(10), default `none`, server default
  `'none'`).
- **Migration:** `require_human_code_review` true → `human`, false → `none`, then the column is dropped. The same
  for the org's `default_require_human_code_review` → `default_pr_review`.
- **Label and help:** the label is "Pull request review". The help texts are exactly the spec's (Goal 1). The
  reviewer label is "Reviewer", whose default option reads "The task's own agent (fresh session)".
- **Marker:** `<!-- megoo:agent-review -->`, at the end of the review body and of every line comment the reviewer
  posts.
- **Escalation reasons and texts:**
  - `agent_merge_failed`: "The agent approved the pull request but couldn't merge it."
  - `agent_review_incomplete`: "The reviewer ended its run without a verdict."
  - `agent_review_unavailable`: "The chosen reviewer can't work on this repository."
  - Accept on `agent_merge_failed` waits for a person to merge (`human_code_review`). Accept on the other two waits
    the same way.
- **Activity (`pr.agent_reviewed`):**
  - "approved PR #n and merged it";
  - "approved PR #n (not merged: {reason})";
  - "requested changes on PR #n · {k} findings", with the summary as a quote.
  - Each is led by the agent's name with the "agent" tag.
- **Panel line during a review run:** "{agent} is reviewing PR #n".
- **Rounds:** shared with piece 3, `MAX_PR_FIX_ROUNDS = 3`. The agent's changes-requested always sends back with
  Agent review (no checkbox, no GitHub association check).
- **Rules from earlier pieces:**
  - migrations only against `megoo_migrate`;
  - one pytest run at a time; the full backend suite runs as `uv run pytest -n auto`;
  - ruff from `backend/`;
  - regenerate `api-types.ts`;
  - commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A different reviewer agent:** enqueueing its run must not overwrite `wf.agent_id`, the task's agent. The fix
   run after it still goes to the task's agent. Pinned in Task 3 by
   `test_a_chosen_reviewer_runs_the_review_and_the_task_agent_fixes`.
2. **The PR merged by a person while the review runs:** when the review run ends (any verdict), the merge is
   settled and the task is Done. Pinned in Task 3 by `test_a_merge_during_the_review_finishes_the_task`.
3. **Existing projects:** `require_human_code_review` true or false maps to `human` or `none`. A workflow already
   in Done keeps the review it froze. Pinned in Task 1 by `test_migration_maps_the_old_checkbox` and
   `test_the_review_mode_is_frozen_at_done`.
4. **The marker'd webhook copies:** the review and its line comments, arriving in any order, are neither shown nor
   a trigger. Pinned in Task 4 by `test_the_agent_review_copy_is_not_shown_or_a_trigger`.
5. **The 4th changes-requested by the agent** escalates instead of a fourth fix. Pinned in Task 3 by
   `test_the_agent_asks_for_changes_three_times_then_a_person_decides`.

---

### Task 1: The setting replaces the checkbox

**Files:**
- Modify: `backend/app/projects/{models,schemas,router,service}.py`. Add `pr_review` and `pr_reviewer_agent_id` (FK
  `agents`, SET NULL), drop `require_human_code_review`, and update PATCH and create. On create, `pr_review` comes
  from the org default.
- Modify: `backend/app/org/{models,router}.py` (`default_pr_review`).
- Modify: `backend/app/workflow/models.py`. `TaskWorkflow.finish_pr_review: String(10)|None` is frozen at Done
  beside `finish_requires_human_review`.
- Modify: `backend/app/workflow/engine.py` (`requires_human_review`, `finishing_option`), and `finish.py`
  (`enter_done` freezes both).
- Create: a hand-edited Alembic migration (the data mapping) on `megoo_migrate`.
- Modify: `frontend/src/components/project/WorkflowSettings.tsx` (select and reviewer select), `lib/workflow.ts`
  (`PR_REVIEW_HELP`), `app/(app)/admin/settings/page.tsx`, `api-types.ts`.
- Modify every test and e2e that sets `require_human_code_review`:
  - backend: `tests/git/test_tracking.py`, `tests/git/test_send_back.py`, `tests/org/test_admin_settings.py`,
    `tests/workflow/test_models.py`, `tests/workflow/test_review_done.py`;
  - frontend: `frontend/e2e/git.spec.ts` and the frontend fixtures.

**Interfaces:**
- Produces: `class PrReview(StrEnum): none, human, agent` in `app/projects/models.py`. The helper
  `engine.pr_review_mode(project, wf) -> PrReview` returns the frozen value once Done began, else the project's.

- [ ] **Step 1: Write the failing tests:**
  - `test_pr_review_defaults_none_and_patches` (in `tests/projects/test_projects.py`): a manager sets `agent` with
    a reviewer, a viewer gets 403, and an unknown value gets 422.
  - `test_migration_maps_the_old_checkbox`: run the migration's data step against rows with true and false (as
    the earlier migration tests do, or downgrade/upgrade on `megoo_migrate` in a test that only reads).
  - `test_the_review_mode_is_frozen_at_done` (in `tests/workflow/test_review_done.py`).
  - vitest: the select with its three help texts, the reviewer select shown only for Agent, and the PATCH body.
  - vitest: the admin default select.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Update every listed test to `pr_review: "human"` or `"none"`.
- [ ] **Step 4: Run** `uv run pytest -n auto` (all backend), `npx vitest run`, tsc and eslint. Expected: PASS.
- [ ] **Step 5: Commit** `feat(projects): pull request review is None, Human or Agent`.

### Task 2: The review run

**Files:**
- Modify: `backend/app/workflow/models.py` (`RunRole.pr_review`).
- Modify: `engine.py`:
  - `ROLE_POLICY` read_only, `FRESH_ROLES`;
  - `enqueue(..., agent_id: uuid.UUID | None = None)`: the run's agent. When given, the run uses it and
    `wf.agent_id` is left alone; the methodology and context are unchanged.
- Modify: `context.py` (`ROLE_KEY`, `BUILD_ROLES` gains `pr_review`), `methodology.py` (`KEYS[Stage.done]` gains
  `"pr_review"`) and `methodology_history.py`.
- Create: `methodology_texts/defaults/pr_review.md`. Its heading is `# Review: the pull request on the host`. It
  covers:
  - read-only; read the PR diff with the host tool;
  - judge against `.megoocolab/design.md`, `.megoocolab/plan.md`, the recorded test runs and the PR's checks;
  - post one comment-type review **from your account** (`gh pr review <n> --comment --body …` plus line comments
    through `gh api`, `glab mr note`, `tea comment`), stating "Verdict: approved" or "Verdict: changes requested",
    with the marker at the end of every body;
  - when approved: wait for the checks (`gh pr checks <n> --watch`; GitLab `glab mr merge <n> --auto-merge`), then
    merge with a merge commit (`gh pr merge <n> --merge`, `glab mr merge`, `tea pulls merge`), never deleting the
    branch;
  - call `submit_pr_review`.
- Create: `backend/app/git/agent_review.py`, with `prompt_section(wf, round) -> str`:

  ```
  ## Pull request to review
  Pull request: <url> (branch <branch>) · review round <r>
  ```
- Modify: `mcp_server/workflow_tools.py`. Add the tool
  `submit_pr_review(key, verdict, summary, findings=[], merged=False, merge_error=None)`:
  - roles `{pr_review}`;
  - `RUNNER_ONLY`;
  - `RUN_NEXT`;
  - it stores `{verdict, summary, findings, merged, merge_error}` in `run.step_result` through
    `agent_review.report(...)`, validating verdict ∈ {approved, changes_requested} and at most 50 findings
    (as `submit_review`);
  - `get_workflow`, `get_document`, `record_decision` and `ask_human` are allowed;
  - `record_tests` is not (reviewers judge records).
- Test: `backend/tests/git/test_agent_review.py`, and the MCP role tables in `tests/mcp/*` and
  `tests/workflow/test_records.py`, `test_methodology.py` (11 keys).

- [ ] **Step 1: Write the failing tests:**
  - `test_review_prompt_names_the_pr_and_round`;
  - `test_submit_pr_review_only_in_a_review_run`;
  - `test_enqueue_with_another_agent_keeps_the_workflow_agent`;
  - the methodology count (11) and its history.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workflow): a review run that reviews the pull request on the host`.

### Task 3: The agent review flow

**Files:**
- Modify: `backend/app/git/send_back.py`. Split `consider` into the gates and `send_back_now(db, wf, task, trigger)
  -> str` (rounds, `pr.sent_back`, set_stage, enqueue the fix to the task's agent). `consider` calls it.
- Modify: `backend/app/git/agent_review.py`:
  - `start_review(db, wf, task) -> None`: picks the reviewer (the project's `pr_reviewer_agent_id`, else the task's
    agent). If an `AgentBinding` doesn't bind it to the project, escalate `agent_review_unavailable`. Otherwise
    enqueue `pr_review` with `agent_id`.
  - `_handle_pr_review`, registered in `ROLE_HANDLERS`:
    - after an answered question (as Finish);
    - record `pr.agent_reviewed {pr_url, pr_number, verdict, summary, findings: k, merged, merge_error, agent_id,
      agent_name}`;
    - approved and merged → `set_stage(done)`, `wait_for(human_code_review)`, `git.queue_refresh` and
      `git.settle_done`;
    - approved, not merged → `set_stage(done)` and escalate `agent_merge_failed`;
    - changes requested → `send_back_now` with trigger kind `"agent_review"` and by = the agent's name. Once the
      rounds are used, it escalates as piece 3 does;
    - nothing reported → one nudge, then escalate `agent_review_incomplete`;
    - in every case, a PR merged meanwhile is settled first (`settle_done` after `wait_for`).
  - `ACCEPT_HANDLERS` for the three reasons: wait for the merge (and settle).
- Modify: `backend/app/workflow/finish.py` (`_handle_finish`) and `send_back._handle_pr_fix`. When
  `pr_review_mode == agent` and the option is pull_request, call `agent_review.start_review` instead of
  `wait_for(human_code_review)`.
- Test: `backend/tests/git/test_agent_review.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_finish_with_agent_review_starts_a_review_run` (the task's agent, a fresh session);
  - `test_approved_and_merged_finishes_once_the_merge_is_seen`;
  - `test_approved_but_not_merged_asks_a_person` (the reason in `pr.agent_reviewed`);
  - `test_changes_requested_sends_back_and_the_fix_is_reviewed_again`;
  - `test_the_agent_asks_for_changes_three_times_then_a_person_decides`;
  - `test_a_chosen_reviewer_runs_the_review_and_the_task_agent_fixes`;
  - `test_an_unbound_reviewer_escalates`;
  - `test_a_merge_during_the_review_finishes_the_task`;
  - `test_no_verdict_nudges_then_escalates`;
  - `test_human_and_none_are_unchanged`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): the agent reviews the pull request, merges it or sends the task back`.

### Task 4: The agent's own review isn't shown twice

**Files:**
- Modify: `backend/app/git/events.py`. Reviews, review comments and comments whose **raw** body contains the marker
  get `data["agent_review"] = True` (checked before the excerpt cuts it).
- Modify: `backend/app/git/activity.py`. Events flagged `agent_review` are skipped: no entry, no fold, no trigger.
- Test: `backend/tests/git/test_events.py` and `test_activity.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_marker_is_found_past_the_excerpt` (a 500-character body ending in the marker);
  - `test_the_agent_review_copy_is_not_shown_or_a_trigger`: line comment, review (changes_requested state), then
    issue comment, all marked, with the checkbox on → no `git.*` entries, no `pr.sent_back`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -n auto tests/git`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): the agent's review on the host isn't shown twice or taken as a person's`.

### Task 5: The words in the UI

**Files:**
- Modify: `frontend/src/lib/workflow.ts` (escalation texts; `ACCEPTABLE_REASONS` gains the three).
- Modify: `frontend/src/components/task/ActivityThread.tsx`. Add `pr.agent_reviewed`, led by `data.agent_name`
  with the "agent" tag, its texts, and the summary as a quote.
- Modify: `frontend/src/components/workflow/WorkflowPanel.tsx`. When the latest run's role is `pr_review` and it is
  running, show "{agent} is reviewing PR #n". The agent's name comes from the run's agent (`useAgentRuns` data),
  else "The reviewer".
- Test: the matching vitest files.

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run`, tsc and eslint. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workflow): see the agent's review on the task`.

### Task 6: End to end

**Files:**
- Modify: `frontend/e2e/git.spec.ts`. A new task **GIT-5** in project GIT, after step 6, with the project switched
  to `pr_review: "agent"` (PATCH):
  - the scenario's `onPrompt("# Review: the pull request on the host")`:
    - in round 1, `mcp("submit_pr_review", {verdict: "changes_requested", summary: "Retry needs a back-off",
      findings: [one]})`;
    - in round 2 (the prompt holds "review round 2"), `mcp("submit_pr_review", {verdict: "approved", summary: "Looks
      good", merged: true})`.
  - The fix run of piece 3 answers as before.
  - The test sets the fake PR #3 merged when the second review run is queued, then expects:
    - Activity "requested changes on PR #3 · 1 findings";
    - "Sent back to its agent";
    - "Fixed and pushed";
    - "approved PR #3 and merged it";
    - the workflow finished.
- [ ] **Step 1: Write the e2e steps.**
- [ ] **Step 2: Run** the git spec on a fresh megoo-e2e stack. Expected: PASS.
- [ ] **Step 3: Run** `uv run pytest -n auto`, the web suite, tsc and eslint, and the whole e2e suite. Expected: all
  green.
- [ ] **Step 4: Commit** `test(e2e): an agent reviews the pull request, sends it back, then merges it`.
