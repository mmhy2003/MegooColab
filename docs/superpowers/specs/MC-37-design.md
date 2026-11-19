# MC-37: show all of an agent's running work, and put the link first in "Running now"

This design goes with mockup **v4** ("Final: Running now (two lines), Admin Agents (newest + more), My agents (Working on)").

## Goal

- On the two Agents pages, an agent shows **every** task, chat and other run it is working on, each as a link. Today Admin → Agents shows only the newest run as plain text, and My agents shows only a count.
- On the Dashboard, each "Running now" row starts with the link to the task or chat, then the agent, then the status. Today the agent's name comes first and a long name pushes the link out of view.

## Decisions

| Question | Answer | Rejected |
|---|---|---|
| Admin → Agents: how to list the runs | **C: the newest run, the rest behind a "+N more" button** that opens them in place (chosen by the human) | A: one line per run, always open. B: chips. |
| Dashboard "Running now" row | **B: two lines**: line 1 the link with the title, line 2 agent, status chip, time (chosen by the human) | A: one line. C: aligned columns. |
| Which Agents pages | **Both**: Admin → Agents and My agents (chosen by the human) | Admin → Agents only. |

Decisions I made, for you to confirm by approving:

1. **My agents lists every run, with nothing to open.** The agent's card has room, so the "+N more" button is used only in the Admin table, where rows should keep one height.
2. **Cron runs and Knowledge Base drafts are listed too.** An agent's count ("3 of 3 running") includes them, so a list that left them out would not add up. A cron run links to its cron page. A draft is plain text ("Knowledge Base draft"), because only the draft's person can open it. The Dashboard keeps leaving drafts out, as it does today.
3. **A chat shows its title** (with the "chat" tag) instead of the word "chat", and **a question shows its key** (for example `MC-Q12`), on all three screens.
4. **A run the viewer cannot open is shown without a link.** This can only happen on My agents, when the owner lost access to a project while their agent was still running there.
5. **The Admin table's status cell also says how many runs are in use** ("3 of 3 running"), with the wording My agents already uses.
6. **`current_run` is removed** from the admin API and replaced by the new `runs` list. Only the Admin → Agents page reads it.

## Architecture

One description of "a run that is running now" is built in one place on the backend and drawn by one set of components on the frontend. The three screens then differ only in layout.

### Backend

- **New `backend/app/agent_runs/running.py`**: the shared query. It takes a filter (the dashboard's scope, or a list of agent ids) and the viewer, and returns `RunningItem` rows, newest started first. It holds the joins that `dashboard/agents.py::running` has today (task, project, workflow, plan steps, question and asking project) plus chat (for the title), cron run and cron (for the name and project).
- **`backend/app/dashboard/agents.py`**: `running()` calls the shared query with the scope. `_runs` adds the cron's project to the scope check, so a cron run is in scope through its project like any other run. `RunningItem` moves to `agent_runs` and `dashboard/schemas.py` imports it from there, so the API name stays the same.
- **`backend/app/agents/service.py`**: `_base_fields` fills a new `runs` field, for the agent's owner and for admins only (the same rule `_machine` uses). Other viewers get an empty list, so the project's agent list does not reveal work in projects a member cannot see. `admin_agents_out` loses its two queries and the `_newest` helper.
- **`backend/app/agents/schemas.py`**: `AgentOut.runs: list[RunningItem] = []`; `AdminAgentOut.current_run` is removed.

No migration, no new endpoint, no new live event. Runs already publish `agents.updated` when they start and finish, which refreshes both Agents pages; the Dashboard already refreshes on live events.

### Frontend

- **New `frontend/src/lib/runs.ts`**: `STAGE_LABEL` and the status text (moved out of `RunningNow.tsx`), plus a `useNow()` hook for the ticking time (also moved out of `RunningNow.tsx`).
- **New `frontend/src/components/runs/RunLink.tsx`**: the link part of a row. Task: the key in mono. Chat: "chat" tag and the title. Question: the question key. Cron: "cron" tag and the cron's name. Draft: "Knowledge Base draft". No `link`: the same text, not clickable.
- **New `frontend/src/components/runs/WorkingOn.tsx`**: the list of an agent's runs for the Agents pages, with a `collapsed` option (newest run plus a "+N more" / "Show less" button with `aria-expanded`). The open state is kept in the component, per row, and is not saved.
- **`components/dashboard/RunningNow.tsx`**: each row becomes two lines, as in the mockup. Line 1: dot, `RunLink`, title. Line 2: agent name (this is what shortens), status chip, time. The queued line and the "All runs" link do not change.
- **`app/(app)/admin/agents/page.tsx`**: the "Current run" column becomes "Working on" and renders `WorkingOn collapsed`; the status cell adds `runsLabel(...)`. The phone card gets the same content under the "Working on" label.
- **`components/agents/AgentsTab.tsx`**: `AgentDetails` gets a "Working on" section between the header and Settings, rendering `WorkingOn` (not collapsed, with titles). It is hidden while the agent runs nothing. The list on the left does not change.
- `frontend/src/lib/api-types.ts` is regenerated with `npm run gen:api`.

## Data and interfaces

`RunningItem` (returned in `DashboardOut.running`, and now in `AgentOut.runs`):

| Field | Change | Meaning |
|---|---|---|
| `kind` | new | `task`, `chat`, `question`, `cron` or `draft` |
| `title` | new | the task's title, the chat's title or the cron's name; null for a question and a draft |
| `question_key` | new | `<KEY>-Q<n>` for an answering run, else null |
| `link` | now nullable | null for a draft, and for a run in a project the viewer cannot open |
| `run_id`, `agent_name`, `started_at`, `task_key`, `stage`, `step`, `steps_total`, `review_round`, `question_from`, `chat_id` | unchanged | |

Links: a task opens the board with its drawer (`task_link`), a chat round opens the chat (`chat_link`), a question opens `/questions/<id>`, a cron opens `/projects/<KEY>/crons/<cronId>`.

Status text: the stage label, with "Step 2 of 5" in Build and the round in Review, as today. For a run with no stage: "Answering" (question), "Running" (cron), "Writing" (draft), "Working" (a freestyle chat turn).

`GET /api/admin/agents`: `current_run` is gone, `runs` is there. `GET /api/agents/mine` (and the create, patch and bindings responses, which share `AgentOut`): `runs` is filled.

## Error handling and edge cases

- **More runs than the limit** (the owner lowered "Runs at once" while runs were going): all of them are listed, and the count reads "3 running, limit 2" as it does today.
- **One run**: no "+N more" button. **No run**: "—" in the Admin table; no "Working on" section on My agents.
- **A run with no start time** sorts last and shows no time.
- **A chat round that was added to the board** is an ordinary task and shows as one (the existing `in_chat` rule).
- **Cron runs on the Dashboard**: today, under "Everything", a cron run appears as "Answering a question" with a link to `/questions/None`. With this change it shows as a cron row with a working link, in every scope its project belongs to.
- **Long titles and names** shorten with an ellipsis. The link's key never shortens, and the full task title is in the link's tooltip in the Admin table.
- **Phone**: the Admin card and the My agents card use the same lists; the lines wrap under the "Working on" label.

## Testing

Tests are written first, as the repository's rules ask.

- **Backend, `tests/agents`**: the admin list returns every running run of an agent, newest first, covering a task, a chat (with its title and chat link), a question (with its key), a cron (name and link) and a draft (no link); queued runs are not listed. `/api/agents/mine` returns the owner's runs. A run in a project the owner cannot access comes back with `link` null. The project agents list returns no runs to a member who is neither owner nor admin.
- **Backend, `tests/dashboard/test_agents.py`**: running rows carry `kind`, `title` and `question_key`; a cron run is in scope through its project and links to the cron page; a draft is still left out.
- **Backend, existing tests that read `current_run`** (`test_dispatch.py`, `test_audit_and_cancel.py`, `tests/agents/test_agents.py`) are changed to read `runs`.
- **Frontend (Vitest)**: `RunningNow.test.tsx`: the link comes before the agent and the status in each row, a chat shows its title, a question its key, the time still ticks. Admin page test: the labels are Owner, Agent, Program, Status, "Working on"; "+2 more" opens the other runs and "Show less" closes them; entries are links. `AgentsTab.test.tsx`: the card lists every run and hides the section when there is none. `RunLink`: a row without a link is not clickable.
- **Browser tests**: `dashboard.spec.ts`, `agents.spec.ts` and `parallel.spec.ts` are updated where they read the old row text, and `parallel.spec.ts` checks that two runs at once both show on the Agents page.

## Out of scope

- The Dashboard's "Agents" card and the "Queued" line.
- The project's agent list and the team page.
- Stopping or opening a run's log from these lists.
- Any change to how runs are counted, limited or dispatched.
