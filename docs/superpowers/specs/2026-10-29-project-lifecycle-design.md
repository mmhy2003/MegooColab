# Project lifecycle: deleting sprints, deleting projects, project status — design

Date: 2026-10-29. Status: agreed in conversation; builder check done; pending the owner's read of this document.

## Why

The owner wanted to delete a test project and found no way to do it. Sprints can't be deleted at all. There is also
no way to say that a project is done: a finished project looks exactly like an active one, keeps its board open to
edits, keeps agents able to start work in it, and keeps appearing in the dashboard's figures. Deleting is the wrong
tool for a real project that is simply over, because it erases its history and everything learned from it.

## What exists today

- **Tasks** can be deleted from the trash icon in the task header. Nothing changes here.
- **Projects**: `DELETE /api/projects/{ref}` exists, admins only. It stops agent runs on the project's tasks, then
  the database cascade removes everything tied to the project, and search entries are purged. Nothing in the app
  calls it. It leaves uploaded attachment files on disk.
- **Sprints**: there is no delete. `tasks.sprint_id` is `ON DELETE SET NULL`, and sprint snapshots cascade.

## Goals

1. **Delete a sprint.** Its tasks go back to the backlog.
2. **Delete a project** from a button, with everything tied to it.
3. **Project status**: Active, Finished, Archived. Each changes what the app does, not just a label.

## Non-goals

- **Showing or hiding action buttons by role across the whole app.** The owner wants this, but as a separate piece
  of work later. This design hides only the new buttons it adds from people who can't use them.
- Restoring a deleted project or sprint. Deletes are final.
- "Not started" or "On hold" statuses. They would change nothing in the app, so they would only be labels that go out
  of date.
- Cleaning up branches and worktrees on agents' machines when a project is deleted. The server can't reach them.

## Anti-goals

- **A delete that leaves pieces behind.** After deleting a project, nothing of it may remain in the database, the
  search index or the upload folder.
- **A delete that's easy to do by accident.** A project delete must be typed, not clicked.
- **Agents still working in a project that's finished.** Closing a project stops the work in it.
- **Losing knowledge by closing a project.** Finished and Archived keep the project's Knowledge Base and what Memory
  learned from it.

## 1. Deleting a sprint

- Who: the same people who can create and complete sprints (managers of the project and admins).
- Any sprint can be deleted: planned, active or completed.
- Its tasks lose their sprint (`sprint_id` set to null): open ones appear in the backlog, done ones simply have no
  sprint. Its burndown snapshots go with it, and it no longer appears in the velocity chart.
- Where: an action on the sprint's panel on the Backlog page, next to its existing actions. It asks first, saying
  how many tasks go back to the backlog and, for an active or completed sprint, that its burndown and velocity
  history is lost.
- `DELETE /api/sprints/{id}` → 204. Boards and the backlog update live (`sprint.*` event), as they do for other
  sprint changes. Audited as `sprint.deleted` with the sprint's name.
- Not allowed in a Finished or Archived project (see 3).

## 2. Deleting a project

- Who: admins only, as today, in any status (see "Settled after the builder check", 1).
- Where: a "Delete project" section at the bottom of the project's Settings page, shown to admins only.
- Confirmation: the dialog lists what goes (tasks, sprints, board, labels, repositories, its Knowledge Base space,
  what Memory learned from it, questions sent to it, attachments) and asks the admin to type the project key. The
  Delete button stays disabled until the key matches.
- What the delete does, on top of today's route:
  - queues Memory's forgetting job, as a task delete does;
  - removes the uploaded files of every task in the project (the folder `<upload root>/<task id>/` per task), after
    the database delete commits, so a failed delete never loses files;
  - the same file clean-up runs when a single task is deleted (its subtasks' folders too), which today also leaves
    files behind.
- Afterwards the admin lands on `/projects`. Other people who have the project open are sent there too, with a short
  "This project was deleted" message, when the live `project.*` event arrives and their next request returns 404.
- Questions this project asked other projects stay with those projects, without the link to the deleted task (as
  today).

## 3. Project status

Three states. New projects start Active.

| | Active | Finished | Archived |
|---|---|---|---|
| Board, backlog, tasks, sprints, columns, labels, repositories | editable | read-only | read-only |
| Agents starting work in it | yes | no | no |
| In the Projects list | yes | yes, with a "Finished" badge | only with "Show archived" on |
| Dashboard figures and widgets | counted | not counted | not counted |
| Search results (its tasks) | yes | yes | no |
| Can be asked a question | yes | yes | no |
| Its Knowledge Base space and Memory | as today | as today | as today |
| Readable by its members | yes | yes | yes |

- **Read-only** means every write that goes through the project write check (`get_project_for(..., write=True)`)
  is refused with 409 `project_closed`. That covers the board, tasks, comments, attachments, sprints, columns,
  labels, repositories, workflow actions, and the agents' MCP tools that write to the project. The frontend shows
  "This project is finished. Reopen it to make changes." (or "archived … Restore it …").
- **Knowledge Base and Memory are left alone.** The KB space stays readable and editable and its documents stay
  searchable, even when the project is archived: knowledge outlives the project.
- **Questions.** A Finished project can still be asked questions, and its agents can still answer them: answering only
  reads. An Archived project is no longer offered as a question target, and asking it returns 409 `project_closed`.
  Questions already sent to it before archiving carry on.
- **Changing status.** Managers of the project and admins. On the project's Settings page, a "Status" section with
  the three choices, and on every page of a closed project a banner ("This project is finished." / "This project is
  archived.") with a Reopen (or Restore) button for those who may change it.
- **Closing a project stops the work in it.** Moving to Finished or Archived:
  - pauses every workflow in progress in the project, the same as pressing Pause on each (running and queued runs
    are cancelled, and the agents' runners are told to stop);
  - the confirmation says how many workflows will be paused, when there are any.
  Reopening leaves them paused, for a person to resume.
- `PUT /api/projects/{ref}/status` with `{ "status": "active" | "finished" | "archived" }`. It must work on a closed
  project (it is how a project is reopened). Audited as `project.status_changed` with the old and new status. Sends
  a `project.updated` event so open pages update live.
- `ProjectOut` gains `status`. The Projects list hides archived projects unless "Show archived" is on (remembered in
  the browser).
- The dashboard counts Active projects only, in every scope. Rows that point into a closed project (a waiting design,
  a mention) disappear from it with the project.

## Settled after the builder check (my calls)

1. **Deleting works in any status.** An admin can delete an Active, Finished or Archived project. The delete route
   is exempt from the closed-project check, like the status route. Archiving first and deleting later is the normal
   path for a test project.
2. **What Memory learned.** Project-scoped memory goes by the database cascade. Conclusions kept at team or
   organisation level that were learned from this project's tasks or answers are handled by the existing forgetting
   job (`mem.forget`, the one a task delete already queues): the project delete queues it too. A conclusion that
   also rests on sources outside the project keeps those; one that rested only on this project is forgotten. The
   dialog's wording: "what Memory learned only from it".
3. **Answering questions is not "work in the project".** The answering path (routing a question, the answering run,
   its MCP tools, approving or rejecting a draft, a person answering) does not go through the closed-project check.
   - Finished: questions to it are routed and answered as usual.
   - Archived: no new questions to it (asking returns 409 `project_closed`). Questions already sent keep going: they
     can still be routed, drafted, approved, rejected or answered by a person.
   - Closing a project does not cancel answering runs.
4. **The boundary of "read-only".** Every write a person or an agent makes to the project's board, tasks, sprints and
   settings goes through one closed-project check. The builder audits the writers (the REST routes, the agents' MCP
   tools for tasks and workflows, a task asking a question) and routes any that bypass `get_project_for(write=True)`
   through it.
   - Internal follow-ups need no check: runner reports for runs that closing has already cancelled, scheduled jobs,
     and git webhooks updating a pull request's state. Closing stops the work, and what arrives afterwards only
     records what already happened.
   - The exemptions: the status route, the delete route and the answering path.
5. **The dashboard counts Active projects only, everywhere.** The scope's project set is Active projects, for every
   section, and My tasks also leaves out tasks in closed projects. Notifications, the Questions page and the
   mention list are not dashboard figures and are unchanged. Links into a closed project still open it, read-only.
   Search drops an Archived project's tasks only.
6. **Questions and Archived projects:** see 3. A task in a closed project can't ask a question (that is a write).
7. **Which workflows closing pauses:** those the engine's Pause applies to (status running or waiting for a person,
   any driver but manual), paused as the person who closes the project. The confirmation's count uses the same
   rule.
8. **Uploads:** task attachments are the only uploaded files (under `<upload root>/<task id>/`). A project delete
   removes the folder of every task the cascade removes, subtasks included. A task delete removes its own folder and
   its subtasks' folders.

## Left to the builder

- The column on `projects` (a string with a server default of `active`), the migration, and backfilling existing
  projects as Active.
- How the write check learns the status (the project row is already loaded there).
- Exact placement and copy of the banner and the Settings sections, following the existing Settings page.
- How a person on a deleted project's page is sent away.

## Testing

- **Backend:**
  - sprint delete: tasks back to the backlog, snapshots gone, managers only, 404 for others' projects;
  - project delete: every related row gone, upload folders removed after commit and kept when the delete fails;
  - task delete removes its and its subtasks' upload folders;
  - status: each write family refused with 409 on Finished and Archived, reads allowed, the status route itself
    allowed, closing pauses workflows and cancels runs, answering runs still start for Finished and not for new
    questions to Archived, archived tasks out of search, the dashboard counts Active only;
  - who may change status and who may delete.
- **Frontend:** the sprint delete action and its message; the delete-project section shown to admins only, the
  typed key enabling the button; the status section and the banner; "Show archived" in the Projects list; the
  "project_closed" message.
- **e2e:** finish a project, see it read-only with the banner, reopen it; archive it and see it leave the Projects
  list; delete a sprint and see its tasks in the backlog; delete a test project by typing its key.
