# MC-158: Subtasks no longer send a Done notification

## Goal

A person hears "PAY-12 is done" only when a real piece of work (a story, task, bug or epic) reaches Done. The plan-step subtasks that the workflow finishes one by one during Build stay silent, so a task with 8 steps sends one Done notification instead of nine.

## Why it happens today

- During Build, each plan step is a subtask (`workflow/documents.py::_start_build` creates them).
- When a step passes, `workflow/build.py::_done_subtask` calls `engine.move_to_category(db, sub, ColumnCategory.done)`.
- `move_to_category` calls `tasks/service.py::notify_done` for every card that enters a Done column from a column that is not Done. It does not look at the card's type.
- A plan subtask has no assignee, so every member of the project's teams gets a `team_task_done` notification for it. The dedupe in `notifications/service.py` is per task id, and each subtask has its own id, so nothing is suppressed.
- A person dragging a subtask to Done (`tasks/service.py::move_task`) goes through the same `notify_done`.

Nothing else on a subtask notifies: plan subtasks are created without an assignee, so `notify_assigned` returns without sending.

## Decisions

| Decision | Chosen | Why |
|---|---|---|
| Which cards stay silent | Every card of type `subtask`, whoever moved it (the workflow, a person, or a chat's agent) | The answer given: "Subtasks never send a Done notification". |
| Who it applies to | Everyone, on every channel (app, email, push, Telegram) | One rule, no setting. Both kinds (`task_done` and `team_task_done`) are skipped. |
| Other types | Stories, tasks, bugs and epics notify exactly as today | Only subtasks were the noise. |
| Where the rule lives | One guard at the top of `notify_done` | Both callers (`move_task` and `move_to_category`) pass through it, so no caller can forget the rule. It sits beside the existing `task.in_chat` guard, which is the same kind of rule. |

Rejected:

- **Silence only the workflow's step subtasks** (a hand-moved subtask would still notify). Rejected by the answer; it also needs the callers to say who moved the card.
- **A personal setting "A subtask is done", off by default.** Rejected by the answer. It would add a notification kind, its defaults, a settings row and an email look for something nobody asked to receive.
- **Filtering in `notifications.notify`.** It is the general delivery function and knows nothing about task types; the rule belongs to the Done notification.

This matches triggers (MC-94), where `task_finished` already fires only for stories, tasks and bugs.

## Architecture

One change in `backend/app/tasks/service.py::notify_done`: return before doing anything when `task.type == TaskType.subtask`, next to the existing `task.in_chat` return. Its docstring gains one clause saying that a subtask tells nobody, because its parent task stands for it.

Also updated, text only:

- The comments on `Kind.task_done` and `Kind.team_task_done` in `backend/app/notifications/models.py`, to say "a task (not a subtask)".
- The module docstring of `backend/tests/notifications/test_task_done.py`.

Not touched: `move_task`, `move_to_category`, `_done_subtask`, `notifications/service.py`, triggers, the frontend. The subtask still moves to Done, its `status_changed` event is still recorded, and live boards still update.

## Data and interfaces

None. No new model, column, migration, endpoint, notification kind or setting. The API schema does not change, so `frontend/src/lib/api-types.ts` is not regenerated.

## Edge cases

- **A subtask with an assignee** (a person made it by hand and assigned it): silent too. The assignee does not get `task_done` for it.
- **A subtask changed to another type, then moved to Done:** it notifies. The type at the moment of the move decides.
- **A story, task or bug under an epic** (it has a parent, but is not a subtask): notifies as today.
- **The parent task finishing:** unchanged. `finish_workflow` moves the parent with `move_to_category`, and the parent's type is not `subtask`.
- **A chat round** (`in_chat`): unchanged, already silent.
- **Notifications already sent for subtasks:** they stay in people's lists. Nothing is deleted.

## Testing

New tests in `backend/tests/notifications/test_task_done.py`, using the helpers that file already uses:

1. The workflow moves a subtask to Done (`engine.move_to_category`): the agent's owner and another team member have no `task_done` and no `team_task_done` rows.
2. A person moves a subtask to Done through the move endpoint: the other team member has no row.
3. A subtask assigned to a person is moved to Done by someone else: the assignee has no row.
4. After the subtask is Done, the parent task moves to Done: each person gets exactly one row, for the parent.

The existing tests in that file must keep passing unchanged: they cover stories and tasks.

## Out of scope

- A per-person setting for subtask notifications.
- Changes to other notification kinds (assigned, mentioned, needs you, agent offline) on subtasks.
- Changes to triggers, which already ignore subtasks.
- Removing the subtask notifications already in people's lists.
- Changes to the labels or hints in Settings → Notifications.
