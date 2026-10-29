# Role-aware actions: show people only what they can do

## Why

The user asked: "show action buttons depending on the user roles, not just check if they can do the action or
not when they click the button." Today many buttons are shown to everyone and the server refuses the click with
"You don't have permission" (403) or "This project is closed" (409). The server's checks are right and stay; the
screens should simply not offer what the person cannot do.

The user skipped the questions; every call below is mine (marked where it is a judgement).

## What the recon found

Most screens already follow the server's flags (workflow `can_act`, agent `can_use`, Knowledge Base `can_write`,
Memory `can_edit`, question `can_answer`...). The gaps, most often hit first:

1. **Finished and archived projects** are read-only on the server, but almost every write control still shows:
   board quick-create and drag, the whole task page (fields, comments, attachments, links, subtasks, workflow
   buttons, design/plan/mockup decisions, questions), backlog create/move and sprint new/start/complete, and the
   project settings editors.
2. **Project settings** General, Columns, Repositories and Labels are editable for members and viewers; only
   admins and the project's managers may change them.
3. **Delete task** shows to every non-viewer; only the task's reporter, a project manager or an admin may delete.
4. **Viewers can drag cards**; the drop is silently ignored.
5. **Team checkboxes** (new project, project settings) list every team; a manager may only attach teams they
   belong to.
6. **Delete team** is offered while the team still has projects; the server refuses it.
7. **Admin pages** Agents, Audit, Settings and Users have no guard of their own (reachable by typing the address;
   the server refuses the data).

## Goals

- One place in the frontend decides a person's rights in a project, from what the API already returns: their
  role and the project's status. *(My call: `canManage(me)` equals the server's project-manager rule on every
  project the person can see, because people only see projects through their own teams.)*
- Gaps 1–7 above are closed.

## Rules for showing an action

- **Never yours to do** (wrong role): the control is **hidden**, or the form is shown **read-only** where people
  still need to see the values (project settings). *(My call.)*
- **Closed project**: everything is read-only, like a viewer's view; the existing banner already says why, and
  managers keep the Status switch to reopen it. *(My call.)*
- **Possible later, not now** (a state, not a role: delete a team that still has projects): the button stays,
  **disabled, with the reason** next to it. *(My call.)*

## Non-goals

- Changing any server check. The server stays the authority.
- State conflicts that are not about roles, which keep their current messages: moving a card the workflow
  controls, changing the agent while its workflow runs, a card move that would start someone else's agent.
- A comment edit/delete UI (none exists today).

## What changes

- **Frontend rights helper** `projectRights(me, project)`: `canWrite` (not a viewer and the project is active),
  `canManage` (admin or manager, and the project is active), `canChangeStatus` (admin or manager, any status),
  `canDeleteProject` (admin), `closed`. Plus `canDeleteTask(me, task, rights)`: `canWrite` and (the reporter or
  `canManage`).
- **Board, backlog, task page**: use `canWrite` where they use "not a viewer" today; sprint actions use
  `canManage`; cards are not draggable without `canWrite`; delete task uses `canDeleteTask`.
- **Project settings**: General, Columns, Repositories and Labels show read-only without `canManage`; Workflow
  settings already have a read-only view and now also use `canManage` (closed-aware); Status keeps
  `canChangeStatus`.
- **Teams**: the list returns `is_member` per team; team checkboxes show only the caller's own teams unless they
  are an admin (a project's existing teams stay listed, checked). The team page gets the true `project_count`
  and disables Delete with "Move or delete this team's projects first." while it is above zero.
- **Admin pages** Agents, Audit, Settings and Users show the same "You don't have permission to do that." card as
  the AI and Git pages for non-admins.

## Left to the builder

Component structure and test shapes, within the rules above.
