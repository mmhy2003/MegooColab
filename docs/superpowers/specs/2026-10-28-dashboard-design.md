# Dashboard — design

Date: 2026-10-28. Status: layout approved in conversation (option A), pending the owner's read of this document.
Mockup: `.superpowers/brainstorm/747-1793195716/content/dashboard.html` (layout A).

## Why

There is no page in MegooColab that answers "what needs me, and what are the agents doing?" The owner has to visit
each board, the notification panel and the Questions page to find out. Agents stall while they wait for a person to
approve a design or a plan, answer a question or review a pull request, so that waiting has to be the first thing you
see. The owner also wants an overview of the work in numbers, updated live while the page is open.

## Goals

- A dashboard that becomes the app's home page. `/` opens it; today `/` redirects to `/projects`.
- Layout A from the mockup: headline numbers across the top; then "Needs you" and "My tasks" on the left with
  "Running now" and "Agents" on the right; then "Workflows by stage", "Tasks finished · last 14 days", "Projects" and
  "Recent activity" in two columns; then "System" across the full width, for admins only.
- A scope switch: **Mine**, **My teams**, **Everything**. Everything is offered to admins only.
- Live updates over the existing WebSocket (`/api/ws`). Nothing on the page needs a reload to be current.
- Every item that names a task links to it (the board with the task drawer open,
  `/projects/<KEY>/board?task=<KEY-n>`, the link format notifications already use).

## Non-goals

- Customising the dashboard: moving, hiding or resizing widgets. The layout is fixed.
- New data. Every figure comes from what the system already stores (see "Widgets").
- Server-Sent Events. The app already has an authorised, rate-limited WebSocket that carries every event the dashboard
  needs, so a second channel would only add work.
- Reports or history beyond the 14-day chart and the 30-day Done figure. The project Reports page stays as it is.
- Acting from the dashboard, for example approving a design in place. Each button opens the task, where the existing
  controls are.

## Anti-goals

- **A dashboard that adds to the refetch storm.** Today an open task page can make about 1,000 API calls a minute
  while an agent works. The dashboard is one request (`GET /api/dashboard`). However many events arrive, it refetches
  at most once every 2 seconds.
- **Showing someone what they cannot see elsewhere.** Every count and row is limited to the projects the viewer can
  already open (`accessible_project_ids`). Admin-only data stays admin-only.
- **A slow home page.** Every section comes from aggregate SQL. Nothing loops over tasks in Python. Target: the
  endpoint answers in under 300 ms with 10,000 tasks.
- **Breaking on a phone.** It must work down to 280 px (Galaxy Fold), like the rest of the app: one column on narrow
  screens, no horizontal scrolling.

## Scope switch

| Scope | Projects counted | "Needs you" holds |
|---|---|---|
| Mine | projects the viewer can open | only items addressed to the viewer (definitions below) |
| My teams | projects the viewer can open (for an admin: projects of the admin's teams) | every waiting item in those projects, each row saying who it waits for |
| Everything (admins) | all projects | every waiting item |

- **Mine** narrows the other widgets as well:
  - "Running now" and "Agents" show the viewer's own agents;
  - the headline numbers, "Workflows by stage", "Tasks finished" and "Projects" count tasks assigned to the viewer
    or to one of the viewer's agents.
- The choice is remembered per browser (in `localStorage`, read and written inside try/catch). The default is My teams.
- `scope=all` from a non-admin gets 403.

## Widgets

"In scope" means the projects and filter the scope switch selects.

**Which tasks count** (my call). The task figures count tasks, stories and bugs only, never subtasks or epics. Those
figures are Open tasks, Done, Overdue, My tasks, Tasks finished, and the Projects bars. The reasons:
- Approving a plan creates one subtask per plan step, unassigned, and Build moves each one to done. Counting them
  would inflate every figure.
- Counting them would also credit the agent's steps to "people".

The parent task stands for its steps.

**Which agent runs count** (my call). Runs that answer a cross-project question have no task. They do count:
- in Running now, the queued list, Failed runs and runs today;
- scoped by the question's target project.

Their row reads "Answering a question from <asking project's key>" in place of a task key and stage, and links to the
Questions page.

**Headline numbers** (7 tiles):

| Tile | Value | Small line |
|---|---|---|
| Need you | how many items "Needs you" holds | how many of them have waited over a day |
| Agents working / online | busy agents / (online + busy) agents | runs queued |
| Workflows in progress | workflows started and not finished | how many projects they are in |
| Open tasks | tasks not in a `done` category column | how many are in `working` or `review` columns |
| Done, last 7 days | tasks with `completed_at` in the last 7 days | the difference from the 7 days before |
| Overdue | open tasks with `due_date` before today | how many of them are assigned to the viewer |
| Failed runs, 24 h | agent runs that failed in the last 24 hours | the success rate (completed / finished) over the same window |

- "Need you" and "Overdue" are drawn in pink when they are above zero.
- "Agents working" is drawn in cyan.
- "Today" means today in the server's time zone (UTC by default).

**Needs you.** Rows, longest-waiting first, up to 10, with "Open all →" leading to the notification panel's full list.
Each row has a coloured label, the task key, a one-line summary, how long it has waited, and one button.

| Label | Source | Addressed to | Button |
|---|---|---|---|
| Approve design / Approve plan | workflow `waiting_human` with `needs` `design_approval` / `plan_approval` | the agent's owner and the task's human assignee | Review |
| Agent asks | `needs = question` | same | Answer |
| Stuck | `needs = escalation` (summary = `escalation_reason`) | same | Look |
| Code review | `needs = human_code_review` (summary = the PR) | same | Review |
| Question to send | cross-project question in status `draft` | the answering agent's owner | Check (opens the Questions page) |
| Question needs a person | cross-project question in status `needs_human` | the people the existing `question_waiting` notification goes to | Answer |
| Mention | the viewer's unread `mentioned` notifications | the viewer | Reply |

- "Addressed to" matches who is notified today (`engine.wait_for`, NOT-1).
- Waiting time starts at the moment the workflow began waiting. If that moment is not stored, the builder adds it (see
  "Left to the builder").
- Under My teams and Everything, each row also names who it waits for.
- Mentions appear only under Mine. They belong to one person.
- Reply marks the mention read (the existing `POST /api/notifications/{id}/read`) before it opens the task. The
  dashboard and the badge then refetch at once, since marking read sends no live event.

**My tasks.** Tasks assigned to the viewer that are open and either overdue, due today or due by the end of this week
(Sunday). Up to 8, overdue first, then by due date. The label says Overdue, Today or This week. It ignores the scope
switch: it is always the viewer's own.

**Running now.** Agent runs in status `running` in scope, newest first.
- Each row: a pulsing dot, the agent's name, the task key, the stage and, for Build, the step progress
  (`current_step` of the plan's step count), and the time since the run started.
- The time ticks in the browser every second without refetching.
- The last row lists queued runs ("Queued: PAY-16 Plan · WEB-33 Design", up to 5 keys, then "and N more").
- "All runs →" goes to the admin Agents page for admins and to "My agents" for others.

**Agents.** Agents bound to projects in scope (under Mine: the viewer's agents).
- Each row: a status dot and label (Working = busy, Idle = online, Offline, from `agent_statuses`), the agent's name,
  and runs started today.
- Working agents come first, then Idle, then Offline, alphabetically within each group.
- If the time an agent went offline is already stored, the row shows it. Otherwise it shows "Offline" alone.
- "Manage →" goes to the same page as above.

**Workflows by stage.** One bar per stage for workflows started and not finished: Brainstorm, Design, Plan, Build,
Review, and Finishing (stage `done`, not yet finished: the finish run, or a code review wait). Each bar is split in
three (my call; the mockup had two):
- agent working (cyan): status `running`, `connect_only` included;
- waiting for a person (amber): `waiting_human`;
- paused or manual (muted): `paused`, and `idle` mid-stage under the manual driver.

The bars add up to the "Workflows in progress" tile. A last bar, Done (green), counts workflows finished in the last
30 days. Bars are scaled to the largest stage bar; Done is always a full bar with its number.

**Tasks finished · last 14 days.** A bar per day (today and the 13 days before), stacked.
- By agents (cyan): tasks completed while assigned to an agent.
- By people (violet): every other completed task.
- The current assignee stands in for the assignee at completion.
- Axis labels on the first, middle and last day; totals in the legend.
- Drawn with plain elements (no chart library), like the mockup.

**Projects.** Projects in scope, by key. Each row: key, name, a progress bar (done green, working+review cyan, the rest
empty), open count, and late count in pink when above zero. "All →" goes to `/projects`.

**Recent activity.** The 8 latest task events in scope, with actor, what happened, task key and time.
- Uses the existing activity wording, so it reads like a task's own activity list.
- Comments are not shown here; mentions already are.

**System** (admins only, any scope). Two columns of status lines with a dot (green fine, amber attention):

| Line | Value | Amber when |
|---|---|---|
| Runners connected | count from the runner registry | none are connected while some agent exists |
| Background jobs | jobs waiting in the PostgreSQL queue | more than 50 are waiting, or the oldest has waited over 5 minutes |
| Search index | Available or Unavailable, and the count of indexed items, as the Search admin page shows | it is unavailable |
| AI provider | whether one is configured, and AI jobs today | none is configured, or a job failed today |
| Memory | when the last learning run finished | the last run failed, or none ran in 26 hours |
| Rate limits hit | `rate_limit.blocked` audit rows in the last 24 hours | above zero |

- The runner registry lives in each backend's memory; it is correct for one backend. Cross-backend counting belongs to
  the high-availability project.
- The search line asks the search engine over HTTP, so its result is cached in the backend for 60 seconds.
- None of these lines send live events. While an admin's dashboard is open, the dashboard query also refetches every
  60 seconds; for non-admins it does not (my call).

## Live updates

- The page uses the socket the app already opens (`connectRealtime`).
- The dashboard's query key is `["dashboard", scope]`. Events that change what it shows invalidate it:
  `task.*`, `question.*`, `agents.*`, `notification.*`, `sprint.*`, `project.*` and `membership.*`.
  `membership.*` already refetches everything.
- The dashboard query refetches at most once every 2 seconds:
  - an event marks it stale;
  - the refetch runs at the end of the 2-second window;
  - events inside the window join that one refetch.

  This throttle belongs to the dashboard query only. Other queries keep their current behaviour.
- On reconnect, the existing "refetch everything" covers the dashboard too.
- The sidebar gets a **Dashboard** entry, first in the list, with the "Need you" count as a pink badge (hidden at
  zero). The count comes from a small `GET /api/dashboard/count` (Mine scope). It refreshes on `task.*`,
  `question.*` and `notification.*` events, under the same at-most-once-every-2-seconds throttle, and never on a timer.

## API

- `GET /api/dashboard?scope=mine|teams|all` returns one JSON object with a key per widget:
  `numbers`, `needs`, `my_tasks`, `running`, `queued`, `agents`, `stages`, `finished_daily`, `projects`, `activity`,
  and `system` (present for admins only).
  - Times are ISO 8601 UTC.
  - Each task carries its `key` (e.g. `PAY-12`), so the frontend can link it without another call.
- `GET /api/dashboard/count` returns `{ "needs_you": n }` (Mine scope).
- Both sit under the general API rate limit. They need no limit of their own.

## Look

- Neon Grid palette and the shadcn-based components already in the app.
- Each widget is a `card`, with an uppercase muted heading, an icon and an optional "→" link.
- The headline tiles use Geist Mono for the numbers.
- Light and dark themes both work.
- The mockup is the reference for spacing, colours and labels.
- An empty widget says so in one muted line ("Nothing needs you." / "No agent is running." / "No tasks due this week.").
- While loading, each widget shows its frame with a muted placeholder, so the layout does not jump.

## Left to the builder

- **When a workflow started waiting.** If `TaskWorkflow` has no time for this, add `waiting_since` (set in `wait_for`,
  cleared when the wait ends) with a migration. Backfill it from `updated_at` for workflows already waiting.
- The SQL behind each section, the response schema names, and how the backend modules are split (a new
  `app/dashboard/` package is expected).
- Component structure on the frontend (`app/(app)/page.tsx` becomes the dashboard).
- The throttle's implementation.

## Testing

- **Backend:**
  - each section's numbers on a small fixture (two projects, one the viewer cannot open, a few tasks, workflows,
    runs, questions);
  - every scope;
  - 403 for `all` from a non-admin;
  - `system` absent for non-admins;
  - nothing from the inaccessible project leaks into any section.
- **Frontend:**
  - each widget renders its data and its empty state;
  - the scope switch requests the right scope and is remembered;
  - Everything is hidden for non-admins;
  - several events within 2 seconds cause one refetch.
- **e2e:** with the dashboard open, a workflow starts waiting for a design approval (set up through the API); the row
  appears and the "Need you" number goes up without a reload, and the sidebar badge shows it. The page also fits a
  280 px-wide screen without horizontal scrolling.
