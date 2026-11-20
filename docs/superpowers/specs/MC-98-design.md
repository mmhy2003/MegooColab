# MC-98 — Finish stage: a fix round for test failures the branch caused

## Goal

When the finish run stops on failing tests and has delivered nothing, a person can click **Fix round** on the "Tests failed at finish" card. The task's agent then fixes the tests in a fresh run, a short review checks the fix, and the finish runs again. A task gets at most 2 fix rounds. The finish agent still never changes code.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| When the card offers Fix round | Whenever nothing was delivered and a round is left, whatever the kinds of the failures. A person always starts it. | You chose this. The diagnosis sometimes says the cause is the environment, which a fix run can't repair, so a person reads it first. Showing the button only with a `new` failure, and starting the first round automatically, were rejected. |
| How many rounds | 2 per task (`MAX_FINISH_FIX_ROUNDS = 2`). Retry doesn't give rounds back. | You chose this. A second attempt helps when the first fix repaired some tests but not all. |
| Stage during the round | Done → Review for the fix and its review, then Done again. | You chose this. The Review stage already runs a fix and then a re-review, and a clean review already enters Done through `finish.enter_done`. The card stays in the board's Review column the whole time, as it does during Done today. |
| Run roles and texts | The fix runs as `final_fix` and its review as `final_review`, each with its own new methodology text (`finish_fix`, `finish_fix_review`), chosen with `key_override` as `design_revision` is for `brainstorm`. | You chose this. Tools, permissions, stage models, session handling and the uncommitted-work rules stay as they are. New roles were rejected (about twelve role tables for the same behaviour), and so was a prompt section on the existing texts (they are written around review findings and a whole-branch review). |
| API | A new action `fix` on `POST /api/tasks/{key}/workflow/escalation`, with a `FIX_HANDLERS` registry next to `ACCEPT_HANDLERS` and `RETRY_HANDLERS`. | You chose this. The endpoint already does the permission check, the "already decided" check, the event and the audit entry. |
| The review of the fix still has findings | A person decides on a new escalation, `finish_fix_not_clean`. Accept runs the finish again with the fix as it is; Retry repeats the review. | This mirrors `final_review_not_clean` after the final review's round 2, as the task asks. Its own reason gives it an accurate text and its own accept handler. You saw this card in the mockup. |
| The fix run commits nothing | The review is skipped and the finish runs again. The round still counts. | There is nothing to review. The fix agent may have repaired the environment instead of the code. |
| Where the round's state lives | A new column `task_workflows.finish_fix_rounds`, and a `fix_round` key in `task_workflows.finish_tests` while a round runs. | `finish_tests` is cleared when Done begins and on Retry, so it can't hold the count. It can hold the "a round is running" marker, because it is cleared exactly when the round ends. |
| Button order | While Fix round is offered it is the main button and Retry is a quiet one. Otherwise Retry is the main button, as today. | You approved this in the mockup. |

## How it works

### One round

1. The finish run calls `report_test_failures`. The card `finish_tests_failed` appears with `delivered = false` (MC-97, unchanged).
2. A person clicks **Fix round**. The engine counts the round, moves the stage from Done to Review and queues a fresh `final_fix` run with the `finish_fix` text. Its prompt carries the failing tests, the finish agent's diagnosis and the test runs the finish recorded.
3. The fix run ends (it has no completion tool; its commit is its report). The engine queues a fresh `final_review` run with the `finish_fix_review` text. Its prompt carries the same failing tests and diagnosis, the commit the fix started from, and the recorded decisions and test runs.
4. The review approves. `finish.enter_done` runs as after any clean final review: it freezes the finish settings again, clears `finish_tests` and queues a fresh finish run.
5. The finish run verifies the tests again. If they pass, it delivers. If they still fail, the card comes back, with Fix round while a round is left.

### The engine

**`engine.decide_escalation`** accepts `fix`. A reason without a fix handler gets 422 `cannot_fix_here`. For `fix` it sets the workflow running, resets `failures` and `nudged`, and calls the handler. The existing event `escalation.decided` and the audit entry `workflow.fix` are recorded as for the other actions.

**`finish._fix_tests_failed`** (registered as `FIX_HANDLERS["finish_tests_failed"]`):

- Refuses with 422 `cannot_fix_here` when the stored report says `delivered`, and with 422 `fix_rounds_exhausted` when `finish_fix_rounds` is already 2. The request's transaction is rolled back, so nothing is recorded.
- Adds 1 to `wf.finish_fix_rounds`. Writes `finish_tests` again without an earlier acceptance and with `fix_round` set to the round's number.
- Records the event `finish.fix_started`.
- `engine.set_stage(Review)`, sets `wf.review_round = 2 + round` and queues `final_fix`.

**A helper, `finish.fix_round(wf)`**, returns the running round's number, or `None`. A round runs when the stage is Review and `finish_tests` has `fix_round`. Every branch below uses it.

**`engine.enqueue`**, while a round runs:

- `final_fix`: `key_override="finish_fix"`, no review findings, and the section "Tests that failed at finish" (below).
- `final_review`: `key_override="finish_fix_review"`, no previous findings, no implementer's report, and the section "The fix to review" (below). The recorded decisions and test runs are included as for any final review.
- Because the prompt is built from the workflow's state, a retry, a nudge, a resume after a pause and a run sent back to commit all get the right text.

**`finish._handle_final_fix`**, while a round runs:

- A question, a late answer and uncommitted work are handled first, as today.
- If the branch head after the run equals the round's base commit (both known), no code changed: event `finish.fix_no_commit`, then `enter_done`. Otherwise it queues `final_review`. It leaves `wf.review_round` as the handler set it (outside a round it still sets 2).
- The round's base commit is `git_before.head` of the round's first `final_fix` run, found the way `build._step_base` finds a step's base, and kept in `finish_tests` as `fix_base`.

**`finish._handle_final_review`**, while a round runs:

- Approved: `enter_done`. The review is not filed to the Knowledge Base, so the task's "Final review" document stays the whole-branch review.
- Changes requested: escalation `finish_fix_not_clean`.
- No verdict: one nudge, then `review_incomplete`, as today.

**`finish._accept_fix_not_clean`** (`ACCEPT_HANDLERS["finish_fix_not_clean"]`): `enter_done`.

**`build.submit_review`** adds `fix_round` to the `review.result` event while a round runs. The review row keeps scope `final`; its round is `wf.review_round` (3 for the first fix round, 4 for the second), so every final review of a task has its own round number.

**`build.enter_review`** resets `finish_fix_rounds` to 0. A whole-branch review starts a new cycle. `enter_done` and Retry don't touch it.

**`finish._raise_card`**, **Finish anyway** and **Retry** are unchanged. After a round the newest run is a finish run again, so Finish anyway resumes its session as today.

### The two prompt sections

Both are MegooColab's own text around agent-written text, which is wrapped as untrusted.

- **"Tests that failed at finish"** (fix run): "Fix round 1 of 2", the start branch, then one untrusted block with each test's name and kind, "and N more" when the list is incomplete, and the diagnosis. After it, the test runs recorded in the Done stage (the commands, counts and failing names), built with `records.test_runs_section`.
- **"The fix to review"** (review run): the same block, and "The fix is every commit after `<fix_base>`". When the base is unknown (a runner too old to report git state) it says to find the commits made after the final review with `git log`.

### The two methodology texts

**`finish_fix.md`** (run by `final_fix`; the same tools as `review_fix.md`):

- First confirm the task branch and a clean tree. The finish run may have left the worktree on the start commit.
- Reproduce each listed failure before changing anything. Treat the diagnosis as a lead, not as fact.
- Fix the cause in the code. Change a test only when the test itself is wrong, and record that with `record_decision`. Never skip, delete or weaken a test to make it pass.
- A `base` or `flaky` test: fix it when the cause is clear and small; otherwise leave it and say so in the commit message.
- When the diagnosis says the failure shows only on the merged result, merge the start branch into the task branch (never rebase), then fix.
- When the cause is the environment and not the code, change no code: call `ask_human`, or end the run without a commit when the environment is repaired.
- Stay inside the failing tests. No new features, no unrelated refactors.
- Run the full suite and the linters, and record the runs with `record_tests`.
- Commit once (`fix(scope): …`, the body lists each test and what was wrong). Don't push. Leave the tree clean.
- The sections "When something fails" (three failed fixes, then `ask_human`), "Evidence before claims" and "Untrusted content" as in `review_fix.md`.

**`finish_fix_review.md`** (run by `final_review`; read-only, `submit_review`):

- Review only the commits of the fix (`git diff <base>..HEAD`), reading the changed code in context.
- Does the fix address the cause of each listed failure?
- Was any test weakened, skipped or deleted to pass? That is `critical`.
- Did anything outside the fix's purpose change?
- Does the change still follow the approved design?
- Do the recorded test runs show a passing full run after the fix? No such run is `important`.
- Severities, the verdict rules, "When you are blocked" and "When to end your turn" as in `review_final.md`. A `changes_requested` verdict goes to a person.

## Architecture

**Backend**

- `backend/app/workflow/engine.py`: `FIX_HANDLERS`; the `fix` branch in `decide_escalation`; the round's branches in `enqueue`; `_previous_findings` and `_implementer_reports` are not called for a round's review.
- `backend/app/workflow/finish.py`: `MAX_FINISH_FIX_ROUNDS`, `fix_round(wf)`, `_fix_tests_failed`, `_accept_fix_not_clean`, the round's branches in `_handle_final_fix` and `_handle_final_review`, the two prompt sections, the registrations, and the module docstring.
- `backend/app/workflow/build.py`: `submit_review` adds `fix_round` to its event; `enter_review` resets the count.
- `backend/app/workflow/models.py`: the column.
- `backend/app/workflow/methodology.py`: `KEYS[Stage.review]` gains `finish_fix` and `finish_fix_review`; the docstring's count of texts. `methodology_history.py`: the two texts' hashes. `methodology_texts/defaults/`: the two files. Startup already inserts version 1 of a key that has no rows.
- `backend/app/workflow/schemas.py`, `router.py`: the API fields below.
- `backend/app/mcp_server/workflow_tools.py`: during a round, the `next` line of `get_workflow` reads "Fix the tests that failed at finish and run the full suite; your run ends when you are done." for the fix run and "Review the fix, then call submit_review with your verdict and findings." for the review. `instructions` already comes from the run's own methodology version.
- One migration in `backend/migrations/versions/`.

**Frontend**

- `EscalationActions.tsx`: the Fix round button, the two hint lines ("Fix round: …. Round 1 of 2." and "Both fix rounds are used."), Retry's look, and `EscalationAction` gains `"fix"`. `ChatEscalation.tsx` uses the same component and needs no change of its own.
- `WorkflowPanel.tsx`: the amber box while a round runs, with `FinishFailures` (without the diagnosis and the runs) under its line. The line is "Fix round 1 of 2 · &lt;agent&gt; is fixing the tests that failed at finish" while the newest run is `final_fix`, and "Fix round 1 of 2 · A reviewer is checking the fix" while it is `final_review`.
- `FinishFailures.tsx`: a prop to leave out the diagnosis.
- `lib/workflow.ts`: `ESCALATION_REASON_TEXT.finish_fix_not_clean` ("The review of the fix round still had findings."), `ACCEPTABLE_REASONS`, and a function that says whether Fix round is offered.
- `ActivityThread.tsx`: the texts below.
- `MethodologyEditor.tsx`: the Review card lists the two new texts.
- `lib/errors` (where API error codes get their texts): `cannot_fix_here` and `fix_rounds_exhausted`.
- `lib/api-types.ts`: regenerated with `npm run gen:api`.

## Data and interfaces

**Database (one migration)**

- `task_workflows.finish_fix_rounds`: integer, not null, default 0. Existing rows get 0, so a card that is open today offers Fix round when nothing was delivered.
- `task_workflows.finish_tests` (JSONB) gains two optional keys: `fix_round` (the running round's number) and `fix_base` (the commit the round's fix started from). No migration is needed for them.

**API**

- `POST /api/tasks/{key}/workflow/escalation`: `action` is `retry`, `accept`, `pause` or `fix`. Errors for `fix`: 422 `cannot_fix_here` (another reason, or the finish already delivered), 422 `fix_rounds_exhausted`, and the existing 409 `already_decided`.
- `WorkflowOut.finish_fix_rounds` (rounds used) and `WorkflowOut.finish_fix_max` (2).
- `FinishTestsOut.fix_round`: the running round's number, or null.
- The frontend offers Fix round when the reason is `finish_tests_failed`, `finish_tests.delivered` is false and `finish_fix_rounds < finish_fix_max`.

**Events on the task**

| Event | Data | Text in the thread |
| --- | --- | --- |
| `escalation.decided` with `action: "fix"` | as today | "Ann chose a fix round" |
| `finish.fix_started` | `{round, of, failures, failing_total}` | "Fix round 1 of 2 started for 2 failing tests" |
| `review.result` with `fix_round` | as today, plus `fix_round` | "Review of fix round 1: approved — 1 minor" |
| `finish.fix_no_commit` | `{round}` | "Fix round 1 changed no code: the finish runs again" |
| `workflow.escalated` with `finish_fix_not_clean` | as today | "The workflow needs a decision. The review of the fix round still had findings." |

The audit log gets `workflow.fix` from `decide_escalation`.

## Error handling and edge cases

- **The finish already delivered.** No Fix round: the code that was delivered would no longer be the code that was fixed. The card is as today.
- **Both rounds are used.** The card shows "Both fix rounds are used." and Retry, Finish anyway and Pause.
- **Retry or Finish anyway instead of a fix.** Unchanged. Retry keeps the count.
- **The fix run asks a question.** It waits for the answer and resumes, as `final_fix` does today.
- **The fix run fails or is cancelled.** The normal retries, then `retries_exhausted`.
- **The fix run leaves work uncommitted.** It is sent back to commit once, then `uncommitted_changes`, as today. The "no code changed" check comes after this one.
- **The git state is unknown** (an old runner). The review always runs, and its prompt says to find the fix's commits with `git log`.
- **Pause and resume during a round.** The newest run's role runs again with the round's text, because the prompt is built from the workflow's state.
- **Settings change during a round.** `enter_done` freezes the finishing option, the pull request review and the known-failures setting again. Nothing was delivered, so the new values apply cleanly. During the round the stage is Review, so the finishing option can be changed on the task again.
- **The tests the fix was for now pass, but another fails.** The card comes back with the new list. The second round, when one is left, gets the new list.
- **A failure that only shows on the merged result** (`merge_local`). The finish agent undid its merge and reported, so nothing was delivered and Fix round is offered. The fix text says to merge the start branch into the task branch first.
- **Customised texts.** `finish_fix` and `finish_fix_review` are new keys, so no customised text is touched. `finish.md` doesn't change.
- **Stage models.** The fix run uses the agent's Build model and the review its Review model, as `final_fix` and `final_review` do.
- **"Running now" lists.** A round's runs read "Review, round 3" (or 4), because `lib/runs.ts` shows the review round. This is left as it is.
- **Chats.** A chat round's escalation uses the same card, so Fix round works there too.
- **Agent-written text** (test names, the diagnosis) is shown as plain text in the UI and wrapped as untrusted in prompts.
- Connect-only and manual workflows and freestyle rounds have no finish runs and are unaffected.

## Testing

**Backend (`uv run pytest`)**

- `tests/workflow/test_finish_failures.py`:
  - `fix` on the card: the count, the stage, `review_round`, `fix_round` in `finish_tests`, the events, and a queued `final_fix` run whose prompt has the `finish_fix` text, the failing tests and the diagnosis, and no "Review findings" section.
  - The fix run ends with a commit: a `final_review` run with the `finish_fix_review` text and the base commit, and no "Previous review findings" or "Implementer's report" section.
  - Approved: Done again, `finish_tests` cleared, a fresh finish run, the count kept, nothing filed to the Knowledge Base.
  - Changes requested: `finish_fix_not_clean`. Accept enters Done; Retry runs the review again.
  - No commit: the review is skipped, the event is recorded, and the finish runs again. Unknown git state: the review runs.
  - A second round works. A third is refused with `fix_rounds_exhausted`. A delivered report and another reason are refused with `cannot_fix_here`, and nothing is recorded.
  - Retry keeps the count. `enter_review` resets it.
  - Pause and resume during the fix and during the review queue the same role with the round's text.
  - A normal final review round (round 1, `final_fix`, round 2) is unchanged, including its Knowledge Base filing.
- `tests/workflow/test_methodology.py`: the two new keys are seeded, and the history ends with the current texts.
- `tests/mcp/test_workflow_tools.py`: `get_workflow` gives the round's `next` line and text.
- `tests/workflow/test_context.py`: the two sections wrap the agent's text as untrusted.
- The escalation endpoint: `fix` is accepted, and an unknown action is still refused.
- The migration goes down and up again.

**Frontend**

- Vitest: `EscalationActions` (Fix round shown and hidden, the hint lines, Retry's look, the click posts `fix`), `WorkflowPanel` (the amber box in both phases), `lib/workflow` (the new reason, the offer rule), `ActivityThread` (the five texts), `MethodologyEditor` (the two keys).
- `tsc --noEmit`, eslint, `npm test`.
- Playwright: one case in `e2e/workflow.spec.ts`, driven the way that spec drives the MC-97 card: the finish reports a new failure, Fix round is clicked, the fix run commits, the review approves, the second finish passes and the workflow finishes.

## Out of scope

- Starting a fix round automatically, without a person.
- A fix round after the finish delivered.
- A baseline before Build and flagging new failures during Build (MC-97's piece 6), and offering bug tasks for known failures. They remain MC-97's other follow-ups.
- A project setting for the number of rounds.
- Changes to `finish.md` and to the classification of failing tests.
- The "Running now" label of a round's runs, and the notification title of an escalation, which keeps showing the reason code.