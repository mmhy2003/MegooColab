# MC-81 design: follow-up tasks proposed with a design, created on approval

## Goal

When a person and the agent agree to split a task into phases, the agent lists the later phases as follow-up tasks on the design it submits. The person reviews that list in the design approval view (untick, edit, add), and approving the design creates the ticked tasks and appends a scope note to the originating task's description. Nothing is created before approval, and workflow runs still cannot create tasks themselves.

The screens are in mockup v1 (three states: reviewing the design, the originating task after approval, a created follow-up task).

## Decisions

Answers the person gave:

| Question | Decision |
|---|---|
| Can the person add a follow-up in the approval view? | **Yes.** They can untick, edit and add tasks. |
| "Related" link as well as the backlink? | **Both.** A `relates` link and a backlink in the description. |
| A design approved a second time on the same task? | **Each approval creates its own version's ticked tasks.** Earlier tasks stay. The scope note the system wrote before is replaced. The view lists what earlier approvals created, so the person can untick duplicates. |
| Show the proposals before the design is submitted? | **No.** The structured list rides only on `submit_design`. During the conversation the agent describes the split in ordinary questions. |
| How does the review reach the approval? | **With the approval request.** Edits live in the page until Approve. Rejected: saving the review on the server as the person edits (new endpoint, live updates, two people editing at once), and letting the button under the mockup approve with a list the person may not have seen. |

Decisions I made from the code:

- **One JSONB column on the document, like plan steps.** `WorkflowDocument.steps` already holds `[{title, detail, subtask_id}]` and is rewritten at approval with the subtask ids. Follow-ups work the same way. A separate table was rejected: the list is small, belongs to exactly one version, and is never queried on its own.
- **A revision that omits `follow_ups` proposes none.** Each version carries its full list (as the task says). `submit_design` returns the count so the agent notices an empty list.
- **A stale page cannot create tasks unseen.** If the version proposes follow-ups, an approval without a `follow_ups` list is refused (`follow_ups_required`). This covers a browser tab opened before the upgrade.
- **The approver is the actor.** The created tasks' reporter, the `follow_up_created` events and the description change are recorded for the person who approved, as `_start_build` does for plan subtasks.
- **Chat rounds are supported with two differences** (see Edge cases): no link and no epic, and the backlink points at the chat.

## Architecture

### Backend

**`app/workflow/follow_ups.py` (new).** Everything specific to follow-ups, so `documents.py` stays small:

- `clean_proposed(items) -> list[dict]`: validates what the agent passed to `submit_design`.
- `clean_reviewed(items) -> list[dict]`: validates what the person sent with the approval.
- `create_on_approval(db, user, task, doc, reviewed) -> None`: creates the tasks, links and events, rewrites `doc.follow_ups`, and writes the scope note.
- `earlier(db, task, doc) -> list[Task]`: follow-up tasks that other approved design versions of this task created and that still exist.
- `backlink(...)` and `scope_note(...)`: build the two texts.

**`app/workflow/documents.py`.**

- `submit(..., follow_ups=None)`: for a design, stores `clean_proposed(follow_ups)`; for a plan, a non-empty list is refused (`follow_ups_forbidden`).
- `submit_connect_only(..., follow_ups=None)`: passes it through.
- `decide(..., follow_ups=None)`: on a design approval, after the document is marked approved and filed and **before** the stage moves to Plan, calls `follow_ups.create_on_approval`. A rejection ignores the list. Everything stays in the one transaction `decide` already runs in.

**`app/mcp_server/workflow_tools.py`.**

- `submit_design(key, markdown, follow_ups=None)`. The docstring says what a follow-up is and that nothing is created before approval. It returns `follow_ups: <count>` with the kind, version and status.
- `get_document` also returns `follow_ups`, so a revising agent can read the list it sent before.
- `TOOL_ROLES` and `board_tools.freestyle_board` are unchanged: no new permission.

**`app/workflow/router.py` and `schemas.py`.** See Data and interfaces.

**Methodology texts.** `brainstorm.md` and `design_revision.md` get the new argument in their tool lists and a short "Follow-up tasks" part:

- use it only when the person agreed to split the work;
- pass the full list on every `submit_design`, including revisions (omitting it proposes none);
- each entry is a title, a type (story, task or bug) and a short description that someone can pick up later without this conversation;
- the person can change the list, and nothing is created until they approve;
- keep the design's "Out of scope" consistent with the list.

Both new hashes are appended to `methodology_history.DEFAULT_HISTORY`, so instances that never customised the texts get them on start-up.

### Frontend

- **`components/workflow/FollowUps.tsx` (new).** The "Follow-up tasks" block. In review mode: one row per task with a checkbox, a type select, a title field and a collapsible description; an "added by you" tag and a remove button on rows the person added; "+ Add a task" (disabled at 10 rows). In read-only mode: the list as text, and on an approved version each entry shows "created" with a link to the task, or "not created".
- **`components/workflow/DocumentView.tsx`.** For a design, renders `FollowUps` between the design text and the comment. It holds the review state (reset when another version is selected), shows the line that says what approving creates, and sends the list with the approval. Review mode needs a submitted version and `can_act`; everyone else sees the list read-only. If a ticked row has an empty title, Approve shows "Give every ticked task a title." and sends nothing.
- **`components/workflow/MockupPanel.tsx`.** When the pending design has `follow_up_count > 0`, "Approve this version" is replaced by "Review follow-up tasks (n)", which scrolls to the Design section (`#document-design`). Otherwise it is unchanged.
- **`components/task/ActivityThread.tsx`.** A `follow_up_created` row: "created follow-up PAY-13: title", with the key linked, like the `agent_task_created` row.
- **`lib/errors.ts`**: texts for the new error codes. API types are regenerated with `npm run gen:api`.

When the agent proposed nothing, a person who can decide still sees the block with "None proposed." and "+ Add a task".

## Data and interfaces

### Database

One migration on `workflow_documents`:

- `follow_ups` JSONB, not null, default `[]`. Entries are `{title, type, description_md, task_id}`; `task_id` is null until a task is created.
- `scope_note` TEXT, nullable: the exact note this approval wrote into the description.

On approval the approved version's `follow_ups` is replaced by the reviewed list (the person's edits and additions included): created entries carry their `task_id`, unticked ones keep null. Rejected and superseded versions keep the agent's list untouched.

### Limits and validation

- At most 10 entries, both from the agent and in the reviewed list.
- `title`: required after trimming, at most 500 characters. `description_md`: at most 4,000 characters. `type`: story, task or bug (default task).
- Errors: `invalid_follow_ups` (not a list, more than 10, a bad entry, an unknown type, a ticked entry without a title), `too_large`, `follow_ups_forbidden` (on a plan), `follow_ups_required` (see Decisions). Texts are NUL-stripped like every other workflow text.

### REST

- `DocumentInfo` gains `follow_up_count: int`.
- `DocumentOut` gains:
  - `follow_ups: [{title, type, description_md, created: bool, task_key: str | null}]`. `created` with a null `task_key` means the task was deleted since.
  - `earlier_follow_ups: [{key, title}]`: what `follow_ups.earlier` returns.
  - `creates_in: {column: str, epic: {key, title} | null} | null`: for a submitted design, where the tasks would go. It feeds the line above Approve.
- `DocumentDecisionIn` gains `follow_ups: [{title, type, description_md, create: bool}] | null`: the whole reviewed list in order, unticked entries included with `create: false`.

### What approval does

For each entry with `create: true`, in list order:

1. `tasks.service.create_task` with the approver as the user: the given title and type, unassigned, no column given (so the project's first before-work column, the same one plan subtasks use), `parent_id` set to the originating task's epic if it has one. The description is the reviewed text followed by a blank line and the backlink:
   `Follow-up of [PAY-12](/projects/PAY/tasks/12), from its [approved design (v2)](/projects/PAY/tasks/12#document-design-v2).`
2. `task_changed(db, new, "task.created")`, so open boards show it.
3. A `TaskLink` of kind `relates` from the originating task to the new one.
4. An event on the originating task: `follow_up_created` with `{key, title, task_id, type, design_version}`.

Then, if at least one task was created, the scope note:

- N is 1 plus the number of this task's follow-up tasks that exist (earlier approvals' and this one's). The note lists all of them.
- Text: `Scope: phase 1 of 3 (per the [approved design](/projects/PAY/tasks/12#document-design-v2)). Phases 2–3 → [PAY-13](/projects/PAY/tasks/13), [PAY-14](/projects/PAY/tasks/14).` With one follow-up: `Scope: phase 1 of 2 (…). Phase 2 → [PAY-13](…).`
- If the newest earlier approved design version has a `scope_note` and the description still contains that exact text, its last occurrence is replaced. Otherwise the note is appended after a blank line. The person's text is never otherwise changed.
- It is written through `tasks.service.update_task`, which records the normal `field_changed` event for `description_md` and queues the memory update. The note is stored in `doc.scope_note`.

`build_prompt` is unchanged: later runs read the note because it is part of the description.

## Error handling and edge cases

- **Rejected or superseded versions create nothing.** Only `decide` with `approve=True` calls `create_on_approval`, and only for the version being approved.
- **Any failure rolls back the approval.** Validation runs before anything is written; an error while creating a task aborts the transaction, so there is never an approved design with half its tasks.
- **Nothing ticked, or nothing proposed:** the design is approved as today, with no tasks, no events and no change to the description.
- **Second approval on the same task:** the view shows "Already created from an earlier approved design: PAY-13, PAY-14." above the list. Nothing is deduplicated automatically.
- **A follow-up task deleted later:** the approved version shows it as created, without a link. The scope note is not updated.
- **The person edited the scope note** before a second approval: the old text is not found, so the new note is appended and the edited one stays.
- **Chat rounds** (`task.in_chat`): the tasks are created on the chat's project board. There is no `relates` link and no epic, because a round is not on the board. The backlink is `From chat: [title](/chats/<id>)`, the form freestyle chats already use, and the scope note links the chat. The event shows in the chat through the shared activity thread.
- **Connect-only agents** (personal token) pass `follow_ups` the same way; the person approves in the same view.
- **Customised methodology texts** are not upgraded. The argument is optional and described in the tool itself, so those instances still work; their agents just are not told when to use it.
- **Very long prompts:** the description is the last thing `build_prompt` trims, from the end, so a description near 60,000 characters can lose the note. Not changed here.
- **Concurrent decisions:** unchanged. `decide` holds the task, workflow and document locks; the second decision gets `already_decided` and creates nothing.

## Testing

Backend (pytest, through `megoocolab-runner services run test`):

- `tests/workflow/test_follow_ups.py` (new): both cleaners (limits, types, empty titles, sizes); approval creates the ticked tasks with the right type, column, epic, no assignee, reporter and backlink; unticked entries create nothing; person-added entries are created; links and `follow_up_created` events; the scope note text for one and several follow-ups; the `field_changed` event; the original description kept; second approval replaces the note and counts earlier tasks; an edited note leads to an append; a chat round gets no link and no epic.
- `tests/workflow/test_documents.py`: `submit` stores the list on a design and refuses it on a plan; a rejection creates nothing; a superseded version's list is never used; `follow_ups_required`; nothing proposed and nothing sent approves as before; a failing creation rolls back the approval.
- `tests/mcp/test_workflow_tools.py`: `submit_design` with and without `follow_ups`, the returned count, `get_document` returning the list, and a workflow run still getting `not_allowed_in_role` from `create_task`.
- `tests/workflow/test_methodology.py`: the history ends with the new hashes.
- The migration goes up, down and up again.

Frontend (Vitest, then `tsc --noEmit` and eslint):

- `FollowUps`: untick, edit, add, remove, the 10-row limit, read-only and approved modes.
- `DocumentView`: the approval sends the reviewed list; a ticked row without a title blocks Approve; a viewer who cannot decide gets the read-only list; the earlier-tasks line.
- `MockupPanel`: the button becomes "Review follow-up tasks (n)" only when the pending design proposes any.
- `ActivityThread`: the `follow_up_created` row and its link.

Browser test (`frontend/e2e/workflow.spec.ts`): a design with two proposed tasks; untick one, add one, approve; the board shows the two new tasks and the originating task's description ends with the scope note.

## Out of scope

- A preview of the proposals on `ask_human`, and saving the review on the server before approval.
- Any direct `create_task` for brainstorm, design or other workflow runs.
- Follow-ups on plans, and follow-ups in another project.
- Assignee, sprint, priority, labels or story points on a follow-up: the person sets those on the created task.
- Keeping the scope note in step when follow-up tasks are later deleted, renamed or moved.
- Listing the follow-ups in the Knowledge Base copy of the approved design.
- Changing how `build_prompt` trims a very long description.
