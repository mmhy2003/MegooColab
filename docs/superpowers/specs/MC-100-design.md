# MC-100: offer bug tasks for known failing tests found at finish

## Goal

Next to each known failing test that a finish reports, a person can click **Create bug task** and get an unassigned bug for that test. When the test already has an open bug in the project, the row shows a link to that bug in place of the button, on every task whose finish sees the test.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Which failures get the offer | `base` and `flaky`, with the same button. `new` failures never get it, also when a person accepted them with Finish anyway. | You chose this. An accepted new failure is merged with the branch, so it gets the offer as `base` at the next task's finish. |
| Where the test name is stored | A new nullable column `tasks.failing_test`. One bug covers one test. | You chose this over a link table (one bug for several tests, with a second "Add to MC-123" action) and over a label (short, shared, and editable, so a rename silently breaks the match). |
| How a test is matched | On a normalised key: whitespace collapsed, and a `:line` or `:line:col` suffix after a file name removed. The bug still shows the name as reported. | You chose this over exact text. Playwright prints `e2e/a.spec.ts:42:5 › title`, and the position changes whenever the file is edited above the test. No fuzzy matching: a wrong match would hide the button for a test that has no bug. |
| Where the button shows | On every `base` or `flaky` row wherever the workflow panel lists the finish's failing tests: after the finish, on the "Tests failed at finish" card, and in the box of a running fix round. | You approved this with the mockup. One rule, no special cases; all three places use the same `FinishFailures` component. |
| Who can click | Anyone who can edit the project's tasks (the panel's existing `disabled` flag, `rights.canWrite`). Read-only people see the links, not the buttons. | You approved this. They are the people who can create a task by hand. |
| Epic | The bug gets no parent. | You approved this. A test that was already broken is not part of the task's epic. |
| What "open" means | The bug is not in a column of category `done`, and is not a chat round kept off the board. | When the bug is Done or deleted and the test still fails at a later finish, the button comes back. |
| Who creates | A person, with one click. No MCP tool, and the finish agent's instructions don't change. | The task asks for this, as with a design's follow-up tasks. |

## Architecture

**Backend, new module `backend/app/workflow/known_bugs.py`** (next to `follow_ups.py`, same shape):

- `test_key(name) -> str`: the match key. Pure function.
- `open_bugs(db, project_id, keys) -> dict[key, Task]`: the open bug for each key. When several are open, the one with the lowest number wins.
- `create(db, user, project, task, name) -> None`: checks the failure, takes the lock, and creates the bug unless an open one exists.

**Backend, touched files:**

- `app/tasks/models.py`: the column, and an index on `(project_id, failing_test)` for rows where it is set. One migration made with `scripts/makemigration.sh`.
- `app/workflow/schemas.py`: `FinishFailureOut` gains `bug: {key, title} | None`.
- `app/workflow/router.py`: `_finish_tests` fills `bug` with one `open_bugs` query for the report's `base` and `flaky` names; the new endpoint (below).
- `app/kb/filing.py`: `_code_span` is reused to put the agent-written test name into the bug's description as inert Markdown (it moves to a shared place if importing it from `kb` would create an import cycle).

**Frontend, touched files:**

- `components/workflow/FinishFailures.tsx`: each row puts its kind chip and its action on a line under the name, as in the mockup. A row with `bug` shows "Bug: MC-131" as a link (the bug's title as tooltip). A `base` or `flaky` row without one shows a ghost button "Create bug task" when the new `onCreateBug` prop is given.
- `components/workflow/WorkflowPanel.tsx` and `EscalationActions.tsx`: pass `onCreateBug` only when the panel is not `disabled`. It uses the panel's existing `post(...)` helper, so the button is disabled while busy, and the workflow, the task and the activity refresh afterwards.
- `components/task/ActivityThread.tsx`: renders the new event, next to `follow_up_created`.
- `lib/api-types.ts`: regenerated with `npm run gen:api`.

## Data and interfaces

**Column** `tasks.failing_test`: `String(300)`, nullable. It holds the match key. It is set only by `known_bugs.create`: it is not in `TaskCreate`, `TaskUpdate`, `TaskOut` or any MCP tool.

**Match key** `test_key(name)`:

1. Collapse every run of whitespace to one space and trim.
2. Remove `:<digits>` or `:<digits>:<digits>` that directly follows a file extension (a dot and 1 to 10 letters or digits).

Examples: `e2e/a.spec.ts:42:5 › finishes` and `e2e/a.spec.ts:57:5 › finishes` give the same key. `tests/x.py::test_y`, `x.test.ts > suite > title` and `npx tsc --noEmit` are unchanged.

**Endpoint** `POST /api/tasks/{key}/workflow/known-failures/bug`, body `{"name": "<the name as listed>"}`, answer `WorkflowOut`. The task is loaded with `get_task_for(..., write=True)`.

1. The workflow's `finish_tests.failures` must hold an entry with exactly this name and kind `base` or `flaky`. If not: 409 `failure_not_listed` (the panel refreshes on a 409, as it does today).
2. Lock the project row, then look for an open bug with the key. If one exists, nothing is created and the answer carries it.
3. Otherwise create the bug with `create_task` (so it is unassigned, in the first before-work column, reported by the person), set `failing_test`, publish `task.created`, add a `relates` link from the task to the bug, and record the event.

**The bug task** (as in the mockup):

- Title: `Failing test: <name>` for `base`, `Flaky test: <name>` for `flaky`, with the name's whitespace collapsed.
- Description: one sentence ("This test already failed on the commit that MC-140 started from, on `develop`." or "This test failed and then passed when it was run again at the finish of MC-140."), then a list: Test, Kind, Seen at (a link to the task and the date), and Command.
- Command is the command of the newest test run the task recorded in the Done stage (not on the start commit) whose failing names include this name. The line is left out when no such run exists.
- A task without a recorded start branch says "the start branch".

**Event** on the source task: kind `finish.bug_created`, actor the person, data `{key, title, task_id, name, kind}`. Shown as "Mohamed created bug MC-141 for the failing test `<name>`", with the key as a link.

## Error handling and edge cases

- **Two people click at once**, on the same task or on two tasks: the project row lock makes the second request see the first one's bug. It creates nothing and shows the link.
- **A stale panel** (the bug was created or closed elsewhere since the page loaded): the server decides at click time. An existing open bug is returned, never duplicated.
- **The report changed** (Retry cleared it, or a new report replaced it): 409 `failure_not_listed`, and the panel refreshes.
- **The bug moved to Done or was deleted**: the row shows the button again. A bug moved back out of Done matches again; if a second bug was created meanwhile, the older one is linked.
- **The task is itself the open bug for the test** (a flaky test that is still flaky at its own finish): the row shows "Bug: this task", and no button.
- **Tests not listed** ("and 5 more"): no offer, since there is no name to store.
- **A chat round's finish**: the bug is a plain board task with no link, and its description points back at the chat, as `follow_ups.py` does.
- **Read-only user or closed project**: 403 `forbidden` or 409 `project_closed` from the existing project access check; the buttons are not shown to them.
- **Agent-written text**: the name is plain text in the panel and the activity, plain text in the title, and a code span in the description.
- **Reports stored before this change** work as they are. Nothing is backfilled.

## Testing

- **Backend**, new `tests/workflow/test_known_bugs.py`:
  - `test_key` on Playwright, pytest, vitest and command names, and on extra whitespace.
  - Creating a bug: type, column, no assignee, no parent, title and description for both kinds, the Command line with and without a matching run, the link, the event.
  - Duplicates: a second click, the same test with another line number, and another task of the same project all get the same bug; another project does not.
  - A bug in Done or deleted: offered again.
  - Refusals: a `new` failure, an unknown name, a read-only user.
  - A chat round: no link.
  - `GET /api/tasks/{key}/workflow` carries `bug` on the matching rows, and on the task that is itself the bug.
- **Frontend**, vitest:
  - `FinishFailures.test.tsx`: the button on `base` and `flaky` rows, none on `new`, the link when `bug` is set, no button without `onCreateBug`, "this task".
  - `WorkflowPanel` test: a click posts the name to the endpoint.
  - `ActivityThread.test.tsx`: the new event's line.
- **End to end**, in `frontend/e2e/workflow.spec.ts` next to the finish tests: a finish with a known failure, click **Create bug task**, the link appears, and the bug is on the board.

## Out of scope

- One bug that covers several tests, and attaching a test to an existing bug by hand.
- Fuzzy matching of names that two agents worded differently.
- An offer for `new` failures, accepted or not.
- Showing or editing `failing_test` on the bug's task page.
- Offers in the pull request description, in notifications, or from the Build baseline (MC-99).
- Creating bugs automatically, or by an agent.