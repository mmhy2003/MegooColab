# Agent Crons: scheduled agent work on a project

Status: in review. Agreed in conversation:
- the owner described a cron as a name, a prompt and a cron-style time;
- the UI helps write the syntax correctly, validates it before saving, and shows it in human-readable form;
- each scheduled time "only runs once on any of the agents", and a cron "has to be related to a project";
- the owner chose **option B** for results ("each cron chooses");
- they answered "approved" to the played-back description, my guesses included;
- cron runs "should run commands", in a throwaway copy of the code.

Calls I made are marked **(my call)**. The mockup is
`.superpowers/brainstorm/768-1793778942/content/agent-crons.html` (git-ignored). Designed alongside the Secrets Store
(`2026-11-04-secrets-store-design.md`): a cron's runs get secrets like any run on its project.

## Why

The owner wants agents to do recurring work on a project without someone starting it each time. Examples:
- a nightly dependency check;
- a weekly sprint summary;
- a hunt for flaky tests.

The pattern in other agent systems (ChatGPT Tasks, Codex automations, Claude Code routines) is that every run leaves
a report you can look back at, you're told when it matters, and the useful ones act inside your system instead of
only sending a message. MegooColab already has the places to act: the project's backlog and its Knowledge Base.

## Goals

1. **A cron** belongs to one project. It has:
   - a **name**, at most 100 characters;
   - a **prompt** (what the agent should do), at most 20,000 characters;
   - a **schedule**: a standard five-field cron expression (minute, hour, day of month, month, day of week);
   - a **time zone**, defaulting to the creator's browser zone;
   - an **agent**: "Any free agent of <project>" by default, or a chosen agent of the project;
   - **what it may do** (goal 5);
   - **when to tell people** (goal 6);
   - **paused** or active.
2. **Writing the schedule** (the owner's ask: help, validate, translate):
   - **Presets** fill in the expression: every hour, every day at…, weekdays at…, every Monday at…, the 1st of the
     month, and custom.
   - **Field labels:** below the expression, its five fields are shown labelled (minute, hour, day of month, month,
     day of week).
   - **Validation as you type:** a mistake is named in plain words ("Hour must be 0–23, you wrote 25") and Save stays
     disabled. The server validates the same way and refuses an invalid expression (422).
   - **In plain words:** a valid schedule is shown in plain English ("Every day at 02:00", "At 16:00 on Friday") with
     the time zone. The next three run times are shown in that zone.
   - **(my call)** Supported syntax: numbers, `*`, ranges `a-b`, lists `a,b`, steps `*/n` and `a-b/n`, and day and
     month names (`MON`, `JAN`). No seconds field, no `@reboot`.
   - **(my call)** A schedule that would run more often than every 5 minutes is refused, to keep agents from being
     flooded.
3. **Exactly once, on one agent.**
   - Each scheduled time of an active cron starts one run on one agent, never two. This holds even with several
     backend processes.
   - **"Any free agent" (my call):** the cron belongs to the project, not to its creator. Any agent bound to the
     project whose owner can still access it is eligible (no check of whom the creator may use), chosen online first,
     then the least busy.
   - **Waiting (my call):** a run is given to its agent when it is due and waits in that agent's queue like any other
     run. The 15 minutes below count from the scheduled time, whether the agent is offline or busy. There is no second
     choice of agent.
   - **(my call)** If the previous run of the cron is still queued or running, the new time is **skipped** and noted
     ("skipped: the previous run was still going").
   - **(my call)** If MegooColab was down at a scheduled time, the cron runs **once** when it is back, and only if
     that was within the last hour. Older missed times are noted as skipped, never run in a burst.
   - **(my call)** If no usable agent is online at the scheduled time, the run waits for one for up to 15 minutes, then
     is noted as skipped ("skipped: no agent online").
   - **Run now** starts one run at once (the same rules about a run in progress apply). **Pause** and **Resume** stop
     and restart the schedule. A run can be stopped like any other.
4. **The run.** A cron's run is an agent run of its own kind, beside task, question and draft runs.
   - **Commands in a throwaway copy (the owner's choice):** a cron run may run any command, as a building agent can
     (the `workspace` policy), so it can run `npm outdated`, the test suite and commands that use secrets. It works in
     its own copy of the code (below).
     - **Thrown away:** whatever it changes there is discarded after the run.
     - **No commits or pushes:** it never commits or pushes, and is told so. The runner resets the copy before each
       run, and the server refuses a run that reports a commit (as the workflow already checks git state).
     - **No code changes:** code changes only through the tasks the cron opens.
   - **Methodology:** it has its own editable methodology text in Admin › Methodology. **(my call)** It lives in the
     new "Knowledge base" tab's neighbour, a "Crons" tab.
   - **Prompt contents:** the cron's prompt, the project's name and key, and the time of this run and of the
     previous one. It also gets the previous run's report, so the agent can say what changed since.
   - **Working folder:** it works in the project's repository on the agent's machine, in a per-cron detached
     worktree (the runner machinery of Knowledge Base drafts).
     - **Fresh code (my call):** at each run the runner fetches the repository's default branch from its remote
       (`origin/<default branch>`) with the machine's own git credentials, as starting a task branch already does,
       and resets the worktree to it.
     - **If the fetch fails,** the run goes ahead on the last fetched commit, and its report says so with the commit
       it used.
   - **Secrets:** it gets the project's secrets and the agent owner's personal secrets, as any run on the project
     does (Secrets Store).
   - **Time limit:** **(my call)** 30 minutes, after which it is stopped and the report says so.
5. **What it may do** (the owner's option B: each cron chooses). Every run writes a **report**; per cron, one of:
   - **Report only:** the report is kept, and people are told per goal 6.
   - **Report and open tasks:**
     - **What it opens:** the agent may create tasks in the project's backlog for real problems it found, labelled
       "from cron" and linked to the run's report.
     - **No duplicates:** it is told to check the project's open tasks first and not open a duplicate. It may
       comment on an existing open task instead.
     - **(my call)** It may create at most 5 tasks per run.
   - **Report and keep one Knowledge Base document:** the cron names one document in the project's space, created
     on the first run if needed. Each run saves a new revision of it, credited to the agent ("<owner> with <agent>",
     summary "Cron: <name>").
     - **The document (my call):** it is created at the top of the project's space, titled after the cron (or a title
       given when setting the cron up). From then on it is followed by its id: moving or renaming it is fine.
     - **If it is deleted,** the next run creates it again.
     - **Each run replaces the whole document** with the current state. The revision history keeps the earlier
       ones, and the form says "Each run rewrites this document".
     - **People's edits:** each run saves over them as a new revision, which is never a conflict.

   **Tools:** the agent reports through a new MCP tool (`submit_cron_report` suggested), with:
   - a summary;
   - findings, each with a title, detail and an optional link to the task it opened or found;
   - what was checked;
   - "nothing new" when there is nothing to report.

   Opening tasks and writing the document use the existing MCP tools, allowed for cron runs only as their cron
   permits.
6. **Telling people.** Per cron, any of:
   - **when it finds something:** the report has findings;
   - **after every run;**
   - **when it fails or is skipped.**

   **Who:** the cron's creator and the project's managers get the notification, linking to the run's report. **(my
   call)** The same notification channels as the rest of MegooColab (in-app, email, push, Telegram per person).
7. **Where it shows.**
   - **Project › Crons:** a new tab. The list shows each cron's name, its prompt's first line, its schedule in plain
     words (with the expression under it), the next run, the last run's outcome and the agent, with **Run now**,
     **Pause** and **Resume**.
   - **A cron's page:** its settings and its run history: each run's time, agent, duration and outcome (findings,
     nothing new, failed, skipped, with why).
   - **A run's report:** its summary, findings with links to the tasks they opened or matched, and what was checked.
   - **Tasks opened by a cron** show "from cron <name>" with a link to the report.
   - **Phones:** all of this fits 280 px wide.
8. **Whose name its actions carry (my call).**
   - As with every run, a cron run acts as its agent's owner. The tasks, comments and revisions it writes are
     credited to that owner with the agent, and its access is that owner's.
   - The cron stays the project's when its creator loses manager rights or leaves. It keeps running, and
     notifications go to the project's managers, plus the creator while they can still see the project.
9. **Who may.**
   - **Create, edit, pause and delete:** the project's managers and admins.
   - **See the list, the history and the reports:** project members.
   - **Run now:** **(my call)** managers and admins.
   - **Agents:** choosing a particular agent needs one the person setting it may use on the project, as chats do
     (`can_use_agent`), checked when the cron is saved. If that agent can no longer work on the project, the run is
     skipped with the reason, and the managers are told.

## Non-goals

- Crons not tied to a project, or across several projects.
- A cron changing code or opening pull requests itself, or a task it opens starting the workflow on its own
  (option C was declined for now).
- Event triggers (on push, on a failed check) instead of times.
- A seconds field, or schedules more often than every 5 minutes.
- Sending reports to outside systems (Slack, webhooks, email digests beyond the usual notifications).

## Anti-goals

- **Two runs** for one scheduled time, or a burst of runs after downtime.
- **A cron that floods the backlog** with duplicate tasks.
- **A schedule saved with a mistake** in it, or saved meaning something other than what the person read in plain
  words.
- **A cron run that changes the project's code:** a commit, a push, or a change left in the person's own checkout.

## Constraints

- **Stack:** the existing pieces: FastAPI and async SQLAlchemy with Alembic, the runner protocol and its
  capabilities, Next.js with TanStack Query.
- **Runner:** cron runs need a runner that supports them (a new capability). Agents on older runners are skipped for
  "any free agent", and a chosen agent on an older runner skips with "runner needs updating".
- **Exactly once:** it must hold with several backend processes and across restarts, so the claim of a scheduled time
  is in the database (one row per cron and scheduled time).
- **Time zones** use the IANA database, daylight saving included: a time that doesn't exist on a DST change is
  skipped that day, and one that occurs twice runs once.

## Testing

- **Backend:**
  - expression validation and plain-word rendering;
  - next run times across DST;
  - exactly one run per scheduled time with concurrent schedulers;
  - skip while a run is still going;
  - catch-up only within the last hour;
  - waiting up to 15 minutes for an agent, then skipping;
  - Run now, Pause and Resume;
  - each "may do" mode, and MCP permissions per mode;
  - the 5-task cap, and task labelling and linking;
  - the Knowledge Base mode's revisions;
  - notifications per setting;
  - permissions.
- **Runner:**
  - the per-cron worktree is fetched and reset to the default branch before each run;
  - changes are discarded after the run;
  - a commit is reported.
- **Frontend:**
  - the schedule helper: presets, field labels, errors, plain words, next runs;
  - the list, the cron page, the history and the report;
  - "from cron" on tasks;
  - phones.
- **e2e:** a cron with "report and open tasks" and **Run now**. The fake agent reports one finding and opens a task.
  The report shows it linked to the new task, labelled "from cron".

## Left to the builder

- **Names:** of tables, routes, the run kind, the capability and the MCP tool.
- **Libraries:** the cron-parsing library on the backend, and how the frontend validates and words expressions (one
  shared set of rules, so the two never disagree).
- **The scheduler loop:** its design, within the exactly-once constraint.
