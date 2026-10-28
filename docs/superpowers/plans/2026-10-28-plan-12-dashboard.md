# Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/` a live dashboard (layout A, ten widgets, Mine / My teams / Everything) backed by one `GET /api/dashboard`, with a Dashboard sidebar entry whose pink badge counts what needs the viewer.

**Architecture:** A new `app/dashboard` package resolves the scope (project set plus an optional "mine" filter) once, then each section runs aggregate SQL. Nothing loops over tasks in Python. The frontend fetches the whole dashboard under `["dashboard", scope]`. The existing WebSocket feeds a trailing throttle that invalidates `["dashboard"]` and `["dashboard-count"]` at most once every 2 s. Widgets are plain components that take their slice of the response as props.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, pytest; Next 16 / React 19 / TanStack Query 5 / Tailwind 4, Vitest + Testing Library; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-dashboard-design.md` (mockup `.superpowers/brainstorm/747-1793195716/content/dashboard.html`, layout A).

## Global Constraints

- **Counted tasks:** task figures count `type IN ('task','story','bug')`. Never subtasks or epics. This applies to Open tasks, Done, Overdue, My tasks, Tasks finished and the Projects bars.
- **Scope:**
  - `mine`: projects the viewer can open (`accessible_project_ids`; all projects for admins), and only tasks assigned to the viewer or to one of the viewer's agents.
  - `teams` (the default): non-admins get `accessible_project_ids`; admins get the projects of their own teams.
  - `all`: admins only, every project; a non-admin gets **403** `forbidden`.
  - Any other value gets 422.
- **Visibility:** no row or count may come from a project outside the scope's project set.
- **"Today":** the server's local date: `datetime.now().astimezone()`, which is UTC in the containers. **"This week"** ends on Sunday: `today + (6 - today.weekday())` days.
- **Links:**
  - task: `/projects/<KEY>/board?task=<KEY-n>`;
  - question: `/questions/<id>`;
  - mention: the notification's own `link`;
  - "Open all →": `/notifications`;
  - "All runs →" / "Manage →": `/admin/agents` for admins, `/settings/agents` for others;
  - Projects "All →": `/projects`.
- **Empty states** (exact copy):
  - "Nothing needs you."
  - "No tasks due this week."
  - "No agent is running."
  - "No agents in scope."
  - "No workflows in progress."
  - "No tasks finished in the last 14 days."
  - "No projects in scope."
  - "No activity yet."
- **Live updates:** query key `["dashboard", scope]` and the badge `["dashboard-count"]`.
  - Throttle window: `THROTTLE_MS = 2_000`, trailing.
  - `task.*`, `question.*` and `notification.*` make both keys stale. `agents.*`, `sprint.*` and `project.*` make only `["dashboard"]` stale. `membership.*` keeps refetching everything at once.
  - Admin dashboards also refetch every 60 s (`refetchInterval: 60_000`). Nothing else uses a timer.
- **Scope memory:** `localStorage["megoo.dashboard.scope"]`, read and written inside try/catch.
- **Look:**
  - Neon Grid tokens; widgets are `card` with an uppercase `text-xs tracking-widest text-muted-foreground` heading, a lucide icon and an optional cyan "→" link.
  - KPI numbers use `font-mono`.
  - Works at 280 px with no horizontal page scroll.
  - Below `lg`, everything is one column.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Plan rulings** (each costs little if wrong):
  - `system` is `null` for non-admins instead of a missing key. This keeps one response type.
  - Success rate = completed / (completed + failed). Cancelled runs are left out; null when there are none.
  - Recent activity skips the streamed agent updates (`agent_message`, `agent_plan`, `agent_tool`, `agent_file_change`, `agent_command`, `agent_permission`) and `question.*`. A working agent would otherwise fill all 8 rows in seconds.
  - `waiting_since` is set by `wait_for` and cleared by a `@validates("status")` hook on `TaskWorkflow` whenever status leaves `waiting_human`. One place clears it, instead of the 15 places that change status.
  - With `/` as the home page, signing in, first-run setup, accepting an invite and the forced password change land on `/` (they land on `/projects` today). The installed app's `start_url` and the sidebar logo point at `/` too.
  - "Question needs a person" rows name their recipients as `anyone on <KEY>` rather than listing every team member.

## Review Focus

1. **An admin in no team** opens the dashboard on the default My teams. They get a working page of zeros and empty states, not an error, and the Everything button is right there. Test: Task 2 `test_admin_in_no_team_gets_an_empty_teams_view`.
2. **A connect-only or manual workflow waits with no agent** (`agent_id` NULL, task assigned to a person). The row is addressed to the assignee alone, with no "None" in "waits for". Test: Task 3 `test_wait_without_an_agent_is_addressed_to_the_assignee`.
3. **Today is Sunday.** "This week" holds nothing beyond today, and a task due today is labelled Today, not This week. Test: Task 2 `test_due_label_on_a_sunday`.
4. **A burst of 50 events in 2 s, then the page closes.** That makes one refetch at most, and none after the socket is closed. Test: Task 6 `stops the pending refetch when closed`.
5. **Long agent names, task titles and question titles at 280 px** truncate inside their row instead of widening the page. Test: Task 9, the mobile check on `/` with a long-titled waiting task.

---

### Task 1: Remember when a workflow started waiting

**Files:**
- Modify: `backend/app/workflow/models.py` (TaskWorkflow), `backend/app/workflow/engine.py:277` (`wait_for`)
- Create: migration in `backend/migrations/versions/` ("workflow waiting since")
- Test: `backend/tests/workflow/test_waiting_since.py`

**Interfaces:**
- Produces: `TaskWorkflow.waiting_since: Mapped[datetime | None]` (timestamptz).
  - Set to `datetime.now(UTC)` by every `engine.wait_for` call.
  - `None` whenever `status` is set to anything other than `waiting_human`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_wait_for_sets_waiting_since_and_leaving_the_wait_clears_it(db, client):
    wf = await _workflow(db, client)            # helper: a PAY task with a running runner workflow
    before = datetime.now(UTC)
    await engine.wait_for(db, wf, Needs.design_approval)
    assert wf.waiting_since is not None and wf.waiting_since >= before
    wf.status = WorkflowStatus.running
    assert wf.waiting_since is None

async def test_a_new_wait_restarts_the_clock(db, client):
    wf = await _workflow(db, client)
    await engine.wait_for(db, wf, Needs.question)
    first = wf.waiting_since
    wf.waiting_since = first - timedelta(hours=1)                 # as if the first wait began an hour ago
    await engine.wait_for(db, wf, Needs.escalation)
    assert wf.waiting_since >= first

def test_migration_backfills_waiting_rows_from_updated_at():
    [path] = Path("migrations/versions").glob("*_workflow_waiting_since.py")
    source = path.read_text()
    assert "waiting_since = updated_at" in source and "status = 'waiting_human'" in source
```

`_workflow` makes a project with `make_project`, inserts a `Task` (via `POST /api/projects/PAY/tasks`) and a `TaskWorkflow(status=running, stage=design, started_at=now)`, and commits. `test_migrations_upgrade_head_is_clean` already covers the schema.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `cd backend && uv run pytest tests/workflow/test_waiting_since.py -q`
  - Expected: FAIL with `AttributeError: ... 'waiting_since'`.

- [ ] **Step 3: Implement.**
  1. Add the column, and `@validates("status")` returning the value after clearing `waiting_since` when the value ≠ `waiting_human`.
  2. In `wait_for`, set `wf.waiting_since = datetime.now(UTC)` after setting the status.
  3. Generate the migration against `megoo_migrate`:
     ```
     DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate bash scripts/makemigration.sh "workflow waiting since"
     ```
  4. Add the backfill `op.execute(...)` to `upgrade()`.
  5. Check `uv run alembic downgrade -1 && uv run alembic upgrade head` on `megoo_migrate`.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/workflow/test_waiting_since.py tests/core/test_migrations.py tests/workflow -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(workflow): remember when a workflow started waiting`.

### Task 2: Dashboard endpoint, scope and task figures

**Files:**
- Create:
  - `backend/app/dashboard/__init__.py`
  - `backend/app/dashboard/scope.py`
  - `backend/app/dashboard/schemas.py`
  - `backend/app/dashboard/tasks.py`
  - `backend/app/dashboard/router.py`
- Modify: `backend/app/main.py` (register `dashboard_router`)
- Test:
  - `backend/tests/dashboard/__init__.py`
  - `backend/tests/dashboard/conftest.py`
  - `backend/tests/dashboard/test_scope.py`
  - `backend/tests/dashboard/test_tasks.py`

**Interfaces:**
- **Produces, `scope.py`:**
  - `ScopeName = Literal["mine", "teams", "all"]`
  - `COUNTED_TYPES = (TaskType.task, TaskType.story, TaskType.bug)`
  - `@dataclass(frozen=True) class Scope`, with fields:
    - `user: User`
    - `name: ScopeName`
    - `project_ids: frozenset[uuid.UUID] | None` (None = every project)
    - `agent_ids: frozenset[uuid.UUID]` (the viewer's own agents)
  - Methods:
    - `def in_projects(self, column) -> ColumnElement[bool]`: `true()` when `project_ids is None`, else `column.in_(project_ids)`.
    - `def mine_tasks(self) -> ColumnElement[bool]`: `true()` unless `name == "mine"`; then `or_(Task.assignee_user_id == user.id, Task.assignee_agent_id.in_(agent_ids))`.
  - `async def resolve_scope(db, user, name: ScopeName) -> Scope` raises `HTTPException(403, "forbidden")` for `all` from a non-admin.
  - `def today() -> date`, `def day_start(d: date) -> datetime` (aware, local midnight), `def week_end(d: date) -> date`.
  - `def task_link(project_key: str, number: int) -> str`.
- **Produces, `schemas.py`** (every later task fills these; field names are the API):
  - `Numbers`: every field defaults to 0 except `success_rate_24h: float | None = None`.
    - `need_you`, `need_you_over_day`
    - `agents_working`, `agents_online`, `runs_queued`
    - `workflows_in_progress`, `workflow_projects`
    - `open_tasks`, `open_in_progress`
    - `done_7d`, `done_prev_7d`
    - `overdue`, `overdue_mine`
    - `failed_24h`, `success_rate_24h`
  - `NeedItem`:
    - `kind: Literal["design_approval","plan_approval","question","escalation","human_code_review","draft_answer","needs_human","mention"]`
    - `ref: str`
    - `title: str`
    - `detail: str | None = None`
    - `since: datetime`
    - `link: str`
    - `waiting_for: list[str] = []`
    - `notification_id: uuid.UUID | None = None`
  - `MyTask`:
    - `key: str`, `title: str`, `due_date: date`
    - `due: Literal["overdue","today","week"]`
    - `link: str`
  - `RunningItem`:
    - `run_id: uuid.UUID`, `agent_name: str`, `started_at: datetime | None`
    - `task_key: str | None`, `stage: Stage | None`
    - `step: int | None`, `steps_total: int | None`, `review_round: int | None`
    - `question_from: str | None`
    - `link: str`
  - `QueuedItem`: `task_key: str | None`, `stage: Stage | None`
  - `Queued`: `total: int = 0`, `items: list[QueuedItem] = []`
  - `AgentItem`:
    - `id: uuid.UUID`, `name: str`
    - `status: Literal["busy","online","offline"]`
    - `runs_today: int`
  - `StageRow`: `stage: Stage`, `running: int`, `waiting: int`, `paused: int`
  - `Stages`: `rows: list[StageRow] = []`, `done_30d: int = 0`
  - `DayFinished`: `day: date`, `agents: int`, `people: int`
  - `ProjectRow`: `key: str`, `name: str`, `open: int`, `in_progress: int`, `done: int`, `late: int`
  - `ActivityRow`:
    - `id: uuid.UUID`, `at: datetime`, `kind: str`, `data: dict`
    - `actor_name: str | None`
    - `task_key: str`
    - `names: dict[str, str]`
  - `SystemOut`:
    - `runners: int`, `agents_exist: bool`
    - `jobs_waiting: int`, `oldest_job_seconds: int | None`
    - `search_available: bool`, `search_documents: int | None`
    - `ai_configured: bool`, `ai_jobs_today: int`, `ai_failed_today: int`
    - `memory_last_at: datetime | None`, `memory_last_failed: bool`
    - `rate_limits_24h: int`
  - `DashboardOut`:
    - `scope: ScopeName`
    - `numbers: Numbers`
    - `needs: list[NeedItem]`
    - `my_tasks: list[MyTask]`
    - `running: list[RunningItem]`
    - `queued: Queued`
    - `agents: list[AgentItem]`
    - `stages: Stages`
    - `finished_daily: list[DayFinished]`
    - `projects: list[ProjectRow]`
    - `activity: list[ActivityRow]`
    - `system: SystemOut | None = None`
  - `NeedsCount`: `needs_you: int`
- **Produces, `tasks.py`:**
  - `async def task_numbers(db, scope) -> dict[str, int]`, with keys:
    - `open_tasks`, `open_in_progress`
    - `done_7d`, `done_prev_7d`
    - `overdue`, `overdue_mine`
  - `async def my_tasks(db, user) -> list[MyTask]`
  - `def due_label(due: date, today: date) -> Literal["overdue","today","week"]`
  - `async def finished_daily(db, scope) -> list[DayFinished]` (14 entries, oldest first)
  - `async def projects(db, scope) -> list[ProjectRow]` (ordered by key)
- **Produces, `router.py`:** `router`, with:
  - `GET /api/dashboard?scope=` (default `teams`) → `DashboardOut`. Sections that later tasks own stay at their defaults for now.
  - `GET /api/dashboard/count` is added in Task 3.
- **Produces, test helpers in `tests/dashboard/conftest.py`:**
  - The `world` fixture returns a `World` dataclass:
    - `viewer`: a member in PAY's team.
    - `other`: a member in WEB's team; the viewer cannot open WEB.
    - `admin`: in no team.
    - `pay`, `web`: project rows.
    - `pay_team`, `pay_manager`.
    - `agent`: "Viewer bot", owned by the viewer, bound to PAY.
    - `other_agent`: "Other bot", owned by `other`, bound to WEB.
  - Helpers:
    - `add_task(db, project, *, type="task", category="before", user=None, agent=None, due=None, completed_at=None, title="T") -> Task`, with the next `number` and the first column of that category.
    - `add_workflow(db, task, *, stage, status, needs=None, driver="runner", agent=None, waiting_since=None, started=True, finished_at=None) -> TaskWorkflow`
    - `add_run(db, agent, *, task=None, question=None, status="running", stage=None, step=None, started_at=None, finished_at=None) -> AgentRun`
    - `add_question(db, project, *, status, from_task=None, draft_agent=None, title="Q") -> Question`
    - `task_key(task) -> str` (`"<KEY>-<number>"`)
    - `column_id(db, project, category) -> uuid.UUID` (the first column of that category)
    - `dash(client, scope=None) -> dict` (asserts 200)
  - Later tasks use them as they are.

- [ ] **Step 1: Write the failing tests.** `test_scope.py`:

```python
async def test_all_is_for_admins_only(client, db, world):
    await login(client, world.viewer)
    assert (await client.get("/api/dashboard", params={"scope": "all"})).status_code == 403
    assert (await client.get("/api/dashboard", params={"scope": "nope"})).status_code == 422
    await login(client, world.admin)
    body = await dash(client, "all")
    assert body["scope"] == "all" and [p["key"] for p in body["projects"]] == ["PAY", "WEB"]

async def test_teams_is_the_default_and_means_the_viewers_projects(client, db, world):
    await login(client, world.viewer)
    body = await dash(client)
    assert body["scope"] == "teams" and [p["key"] for p in body["projects"]] == ["PAY"]

async def test_teams_for_an_admin_is_the_admins_teams(client, db, world):
    db.add(TeamMember(team_id=world.pay_team.id, user_id=world.admin.id)); await db.commit()
    await login(client, world.admin)
    assert [p["key"] for p in (await dash(client, "teams"))["projects"]] == ["PAY"]

async def test_admin_in_no_team_gets_an_empty_teams_view(client, db, world):
    await login(client, world.admin)
    body = await dash(client, "teams")
    assert body["projects"] == [] and body["numbers"]["open_tasks"] == 0 and body["needs"] == []

async def test_system_is_null_for_non_admins(client, db, world):
    await login(client, world.viewer)
    assert (await dash(client))["system"] is None
```

`test_tasks.py`:

```python
async def test_task_numbers_count_tasks_stories_and_bugs_only(client, db, world):
    now, yesterday = datetime.now(UTC), today() - timedelta(days=1)
    await add_task(db, world.pay, category="before")
    await add_task(db, world.pay, category="working", type="story")
    await add_task(db, world.pay, category="review", type="bug", due=yesterday, user=world.viewer)
    await add_task(db, world.pay, category="before", type="subtask", due=yesterday)
    await add_task(db, world.pay, category="before", type="epic")
    await add_task(db, world.pay, category="done", completed_at=now - timedelta(days=2), due=yesterday)
    await add_task(db, world.pay, category="done", completed_at=now - timedelta(days=9))
    await add_task(db, world.pay, category="done", type="subtask", completed_at=now - timedelta(days=1))
    await add_task(db, world.web, category="working", due=yesterday)          # not the viewer's project
    await add_task(db, world.web, category="done", completed_at=now)
    await login(client, world.viewer)
    n = (await dash(client))["numbers"]
    assert (n["open_tasks"], n["open_in_progress"]) == (3, 2)
    assert (n["done_7d"], n["done_prev_7d"]) == (1, 1)
    assert (n["overdue"], n["overdue_mine"]) == (1, 1)

async def test_mine_counts_tasks_of_the_viewer_and_their_agents(client, db, world):
    await add_task(db, world.pay, user=world.viewer)
    await add_task(db, world.pay, agent=world.agent)
    await add_task(db, world.pay, user=world.pay_manager)
    await login(client, world.viewer)
    assert (await dash(client, "teams"))["numbers"]["open_tasks"] == 3
    assert (await dash(client, "mine"))["numbers"]["open_tasks"] == 2

async def test_my_tasks_are_the_viewers_own_due_this_week_whatever_the_scope(client, db, world):
    t = today()
    await add_task(db, world.pay, user=world.viewer, due=t + timedelta(days=1), title="soon")
    await add_task(db, world.pay, user=world.viewer, due=t, title="today")
    await add_task(db, world.pay, user=world.viewer, due=t - timedelta(days=3), title="late")
    await add_task(db, world.pay, user=world.viewer, due=week_end(t) + timedelta(days=1), title="next week")
    await add_task(db, world.pay, user=world.viewer, due=t - timedelta(days=1), category="done", title="done")
    await add_task(db, world.pay, user=world.viewer, due=t, type="subtask", title="step")
    await add_task(db, world.pay, user=world.pay_manager, due=t, title="theirs")
    await login(client, world.viewer)
    for scope in ("mine", "teams"):
        rows = (await dash(client, scope))["my_tasks"]
        expected = ["late", "today"] + (["soon"] if t + timedelta(days=1) <= week_end(t) else [])
        assert [r["title"] for r in rows] == expected
    assert rows[0]["due"] == "overdue" and rows[1]["due"] == "today"
    assert rows[0]["link"].startswith("/projects/PAY/board?task=PAY-")

async def test_my_tasks_stops_at_eight(client, db, world):
    for i in range(9):
        await add_task(db, world.pay, user=world.viewer, due=today() - timedelta(days=i + 1))
    await login(client, world.viewer)
    assert len((await dash(client))["my_tasks"]) == 8

def test_due_label_on_a_sunday():
    sunday = date(2026, 11, 1)
    assert week_end(sunday) == sunday
    assert due_label(sunday, sunday) == "today"
    assert due_label(date(2026, 10, 31), sunday) == "overdue"
    assert due_label(date(2026, 10, 29), date(2026, 10, 28)) == "week"

async def test_finished_daily_splits_agents_and_people_over_14_days(client, db, world):
    start = day_start(today())
    await add_task(db, world.pay, category="done", agent=world.agent, completed_at=start + timedelta(hours=1))
    await add_task(db, world.pay, category="done", user=world.viewer, completed_at=start + timedelta(hours=2))
    await add_task(db, world.pay, category="done", completed_at=start - timedelta(days=13) + timedelta(hours=1))
    await add_task(db, world.pay, category="done", completed_at=start - timedelta(days=14) + timedelta(hours=1))
    await add_task(db, world.pay, category="done", type="subtask", agent=world.agent, completed_at=start)
    await add_task(db, world.web, category="done", completed_at=start + timedelta(hours=1))
    await login(client, world.viewer)
    days = (await dash(client))["finished_daily"]
    assert len(days) == 14
    assert days[-1] == {"day": today().isoformat(), "agents": 1, "people": 1}
    assert days[0] == {"day": (today() - timedelta(days=13)).isoformat(), "agents": 0, "people": 1}

async def test_projects_rows(client, db, world):
    await add_task(db, world.pay, category="before", due=today() - timedelta(days=1))
    await add_task(db, world.pay, category="working")
    await add_task(db, world.pay, category="done", completed_at=datetime.now(UTC))
    await add_task(db, world.pay, type="subtask")
    await login(client, world.viewer)
    [row] = (await dash(client))["projects"]
    assert row == {"key": "PAY", "name": "Project PAY", "open": 2, "in_progress": 1, "done": 1, "late": 1}
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/dashboard -q`
  - Expected: FAIL with `ModuleNotFoundError: app.dashboard` (or 404s).

- [ ] **Step 3: Implement** the Interfaces above.
  - `resolve_scope`:
    - Admins under `teams` get the projects of `user_team_ids` via `ProjectTeam`.
    - `agent_ids` = `select(Agent.id).where(Agent.owner_id == user.id)`.
  - `task_numbers` is one `select` over `Task` joined to `BoardColumn`, with `func.count().filter(...)` per key.
  - `finished_daily` groups by `func.date_trunc('day', completed_at)` in the server zone (local date of `completed_at`) and fills missing days with zeros in Python. That loop is 14 iterations, not a loop over tasks.
  - The router builds `DashboardOut` from the sections that exist so far.
  - Register the router in `main.py`.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/dashboard -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(dashboard): endpoint, scope switch and task figures`.

### Task 3: Needs you, workflows by stage, and the count

**Files:**
- Create: `backend/app/dashboard/needs.py`, `backend/app/dashboard/workflows.py`
- Modify: `backend/app/dashboard/router.py` (fill `needs`, `numbers.need_you*`, `stages`, `numbers.workflows_*`; add `/api/dashboard/count`)
- Test: `backend/tests/dashboard/test_needs.py`, `backend/tests/dashboard/test_workflows.py`

**Interfaces:**
- Consumes: `Scope`, `resolve_scope`, the test helpers (Task 2), and `TaskWorkflow.waiting_since` (Task 1).
- **Produces:**
  - `async def needs(db, scope, limit: int = 10) -> tuple[list[NeedItem], int, int]`, returning (rows, total, over a day old).
  - `async def stages(db, scope) -> tuple[Stages, int, int]`, returning (stages, workflows in progress, projects they are in).
  - `GET /api/dashboard/count` → `NeedsCount` (always the `mine` scope).
- **Rules:**
  - **Addressed to the viewer:**
    - A workflow wait: the owner of `coalesce(wf.agent_id, task.assignee_agent_id)`, or `task.assignee_user_id`.
    - A `draft` question: the owner of `draft_agent_id`.
    - A `needs_human` question: members of the target project's teams whose role is not `viewer`.
    - A mention: the viewer's unread `Kind.mentioned` notifications. These appear under `mine` only.
  - **Under teams/all,** every item in the project set, with `waiting_for` holding:
    - the owner's and assignee's names (no None, no duplicates); or
    - the draft agent owner's name; or
    - `anyone on <KEY>`.
  - **`since`:** `waiting_since` (fallback `updated_at`), `Question.updated_at`, or `Notification.created_at`.
  - **`detail`:**
    - `question`: the newest open `WorkflowQuestion.body`;
    - `escalation`: `escalation_reason`;
    - `human_code_review`: `pr_url`;
    - `draft_answer` / `needs_human`: `None`;
    - `mention`: the notification `body`.
  - **`ref`:** the task key, or `<KEY>-Q<n>` for questions.
  - **`title`:** the task title, the question title, or the notification title.
  - **Order:** `since` ascending, then cut to `limit`. `total` counts everything.
  - **Stages:** workflows with `started_at IS NOT NULL` and status ≠ `finished`, grouped by `stage`:
    - `running` = status `running`;
    - `waiting` = `waiting_human`;
    - `paused` = `paused` or `idle`.
    - Rows are always the six stages in `Stage` order.
    - `done_30d` = finished with `finished_at` in the last 30 days.
    - Under `mine`, only workflows whose task passes `mine_tasks()`.

- [ ] **Step 1: Write the failing tests.** `test_needs.py`:

```python
async def test_mine_holds_what_is_addressed_to_the_viewer(client, db, world):
    old = datetime.now(UTC) - timedelta(days=2)
    design = await add_task(db, world.pay, agent=world.agent, title="Refunds")
    await add_workflow(db, design, stage="design", status="waiting_human", needs="design_approval", agent=world.agent, waiting_since=old)
    asks = await add_task(db, world.pay, user=world.viewer, title="Colours")
    wf = await add_workflow(db, asks, stage="brainstorm", status="waiting_human", needs="question", driver="connect_only")
    db.add(WorkflowQuestion(task_id=asks.id, stage="brainstorm", body="Which colour?")); await db.commit()
    stuck = await add_task(db, world.pay, user=world.pay_manager)                     # someone else's
    await add_workflow(db, stuck, stage="build", status="waiting_human", needs="escalation")
    await add_question(db, world.pay, status="draft", draft_agent=world.agent, title="Retry policy?")
    await add_question(db, world.pay, status="needs_human", title="Who owns billing?")
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="Pat mentioned you", body="can you check?",
                        link="/projects/PAY/board?task=PAY-1"))
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="read", body="", link="/x", read_at=datetime.now(UTC)))
    leak = await add_task(db, world.web, user=world.viewer)                              # WEB: never shown
    await add_workflow(db, leak, stage="plan", status="waiting_human", needs="plan_approval")
    await add_question(db, world.web, status="needs_human")
    await db.commit()
    await login(client, world.viewer)
    body = await dash(client, "mine")
    kinds = [n["kind"] for n in body["needs"]]
    assert kinds[0] == "design_approval"                                                  # longest waiting first
    assert sorted(kinds) == sorted(["design_approval", "question", "draft_answer", "needs_human", "mention"])
    by = {n["kind"]: n for n in body["needs"]}
    assert by["question"]["detail"] == "Which colour?"
    assert by["design_approval"]["link"] == f"/projects/PAY/board?task={by['design_approval']['ref']}"
    assert by["draft_answer"]["ref"].startswith("PAY-Q") and by["draft_answer"]["link"].startswith("/questions/")
    assert by["mention"]["notification_id"] and by["mention"]["link"] == "/projects/PAY/board?task=PAY-1"
    assert (body["numbers"]["need_you"], body["numbers"]["need_you_over_day"]) == (5, 1)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 5}

async def test_teams_holds_every_wait_with_who_it_waits_for_and_no_mentions(client, db, world):
    stuck = await add_task(db, world.pay, user=world.pay_manager)
    await add_workflow(db, stuck, stage="build", status="waiting_human", needs="escalation", agent=world.agent)
    await add_question(db, world.pay, status="needs_human")
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="m", body="", link="/x")); await db.commit()
    await login(client, world.viewer)
    rows = (await dash(client, "teams"))["needs"]
    assert {r["kind"] for r in rows} == {"escalation", "needs_human"}
    by = {r["kind"]: r for r in rows}
    assert sorted(by["escalation"]["waiting_for"]) == sorted([world.viewer.name, world.pay_manager.name])
    assert by["needs_human"]["waiting_for"] == ["anyone on PAY"]

async def test_wait_without_an_agent_is_addressed_to_the_assignee(client, db, world):
    t = await add_task(db, world.pay, user=world.viewer)
    await add_workflow(db, t, stage="review", status="waiting_human", needs="human_code_review", driver="manual")
    await login(client, world.viewer)
    [row] = (await dash(client, "teams"))["needs"]
    assert row["waiting_for"] == [world.viewer.name]
    assert [r["kind"] for r in (await dash(client, "mine"))["needs"]] == ["human_code_review"]

async def test_needs_keeps_ten_and_counts_all(client, db, world):
    for i in range(12):
        t = await add_task(db, world.pay, user=world.viewer)
        await add_workflow(db, t, stage="plan", status="waiting_human", needs="plan_approval",
                           waiting_since=datetime.now(UTC) - timedelta(minutes=i))
    await login(client, world.viewer)
    body = await dash(client, "mine")
    assert len(body["needs"]) == 10 and body["numbers"]["need_you"] == 12

async def test_viewers_are_not_asked_to_answer_questions(client, db, world):
    world.viewer.role = Role.viewer; await db.commit()
    await add_question(db, world.pay, status="needs_human")
    await login(client, world.viewer)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 0}
```

`test_workflows.py`:

```python
async def test_stage_bars_split_running_waiting_and_paused(client, db, world):
    now = datetime.now(UTC)
    for stage, status, driver in [("brainstorm", "running", "runner"), ("design", "waiting_human", "runner"),
                                  ("plan", "paused", "runner"), ("build", "idle", "manual"),
                                  ("build", "running", "connect_only"), ("review", "waiting_human", "runner"),
                                  ("done", "running", "runner")]:
        await add_workflow(db, await add_task(db, world.pay), stage=stage, status=status, driver=driver)
    for days in (1, 20, 40):
        await add_workflow(db, await add_task(db, world.pay), stage="done", status="finished",
                           finished_at=now - timedelta(days=days))
    await add_workflow(db, await add_task(db, world.pay), stage="brainstorm", status="idle", started=False)
    await add_workflow(db, await add_task(db, world.web), stage="build", status="running")
    await login(client, world.viewer)
    body = await dash(client)
    rows = {r["stage"]: (r["running"], r["waiting"], r["paused"]) for r in body["stages"]["rows"]}
    assert list(rows) == ["brainstorm", "design", "plan", "build", "review", "done"]
    assert rows == {"brainstorm": (1, 0, 0), "design": (0, 1, 0), "plan": (0, 0, 1), "build": (1, 0, 1),
                    "review": (0, 1, 0), "done": (1, 0, 0)}
    assert body["stages"]["done_30d"] == 2
    assert (body["numbers"]["workflows_in_progress"], body["numbers"]["workflow_projects"]) == (7, 1)
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/dashboard/test_needs.py tests/dashboard/test_workflows.py -q`
  - Expected: FAIL (the needs list is empty, the stage rows are missing, and the count route 404s).

- [ ] **Step 3: Implement** per the Rules.
  - Use one query per source (workflow waits, draft questions, needs-human questions, mentions), each already filtered by scope and recipient.
  - Merge and sort the four small lists in Python.
  - Names come from one `select(User.id, User.name)` for the recipient ids.
  - `/api/dashboard/count` calls `needs(db, await resolve_scope(db, user, "mine"), limit=0)` and returns the total.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/dashboard -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(dashboard): needs you, workflows by stage and the sidebar count`.

### Task 4: Agents, running and queued runs

**Files:**
- Create: `backend/app/dashboard/agents.py`
- Modify:
  - `backend/app/runner/registry.py` (add `connected_count`)
  - `backend/app/dashboard/router.py` (fill `running`, `queued`, `agents`, `numbers.agents_*`, `runs_queued`, `failed_24h`, `success_rate_24h`)
- Test: `backend/tests/dashboard/test_agents.py`

**Interfaces:**
- Consumes: `Scope`, the helpers, and `app.agents.service.agent_statuses`.
- **Produces:**
  - `RunnerRegistry.connected_count() -> int`: live, not-closed connections.
  - `async def agents(db, scope) -> list[AgentItem]`
  - `async def running(db, scope) -> list[RunningItem]`
  - `async def queued(db, scope) -> Queued`
  - `async def run_numbers(db, scope) -> dict`, with keys `agents_working`, `agents_online`, `runs_queued`, `failed_24h` and `success_rate_24h`.
- **Rules:**
  - **Agents in scope:** agents with an `AgentBinding` whose project is in the set (every agent when the set is None). Under `mine`, only `owner_id == user.id`.
  - **Agent order:** busy, then online, then offline; by name within each group.
  - **`runs_today`:** runs with `started_at >= day_start(today())`.
  - **A run is in scope** when its task's project is in the set, or (answering runs) its question's `target_project_id` is. Under `mine`, only runs of the viewer's agents.
  - **`running`:** status `running`, newest `started_at` first.
    - `steps_total` = `jsonb_array_length(steps)` of the task's newest `approved` plan document, only for stage `build`.
    - `review_round` = the workflow's `review_round` for stage `review`, else None.
    - `question_from` = the key of the asking task's project (None when the question has no `from_task_id`).
    - `link` = the task link, or `/questions/<id>`.
  - **`queued`:** status `queued`, oldest `created_at` first, 5 items, with `total`.
  - **Failed runs:** `failed_24h` counts runs with status `failed` and `finished_at` within 24 h. `success_rate_24h` = completed / (completed + failed) over the same window, or None.

- [ ] **Step 1: Write the failing tests**

```python
async def test_agents_are_ordered_working_idle_offline(client, db, world, monkeypatch):
    idle = Agent(owner_id=world.pay_manager.id, name="Alpha", program="codex")
    off = Agent(owner_id=world.pay_manager.id, name="Aardvark", program="codex")
    db.add_all([idle, off]); await db.flush()
    db.add_all([AgentBinding(agent_id=a.id, project_id=world.pay.id, local_path="/w") for a in (idle, off)])
    await db.commit()
    task = await add_task(db, world.pay)
    await add_run(db, world.agent, task=task, status="running", started_at=datetime.now(UTC))
    monkeypatch.setattr(registry, "available_agents", lambda owner: {idle.id} if owner == world.pay_manager.id else set())
    await login(client, world.viewer)
    body = await dash(client)
    assert [(a["name"], a["status"], a["runs_today"]) for a in body["agents"]] == [
        ("Viewer bot", "busy", 1), ("Alpha", "online", 0), ("Aardvark", "offline", 0)]
    assert (body["numbers"]["agents_working"], body["numbers"]["agents_online"]) == (1, 2)
    assert [a["name"] for a in (await dash(client, "mine"))["agents"]] == ["Viewer bot"]

async def test_running_rows_show_build_progress_and_answering_runs(client, db, world):
    task = await add_task(db, world.pay)
    await add_workflow(db, task, stage="build", status="running", agent=world.agent)
    db.add(WorkflowDocument(task_id=task.id, kind="plan", version=1, body_md="", status="approved",
                            steps=[{"title": "a"}, {"title": "b"}, {"title": "c"}]))
    await db.commit()
    await add_run(db, world.agent, task=task, stage="build", step=2, started_at=datetime.now(UTC) - timedelta(minutes=5))
    asking = await add_task(db, world.web)
    q = await add_question(db, world.pay, status="routed", from_task=asking)
    await add_run(db, world.agent, question=q, started_at=datetime.now(UTC))
    await add_run(db, world.other_agent, task=await add_task(db, world.web))                 # WEB: not shown
    await login(client, world.viewer)
    rows = (await dash(client))["running"]
    assert [(r["task_key"], r["question_from"]) for r in rows] == [(None, "WEB"), (task_key(task), None)]
    build = rows[1]
    assert (build["agent_name"], build["stage"], build["step"], build["steps_total"]) == ("Viewer bot", "build", 2, 3)
    assert rows[0]["link"] == f"/questions/{q.id}"

async def test_queued_lists_five_and_counts_all(client, db, world):
    for _ in range(7):
        await add_run(db, world.agent, task=await add_task(db, world.pay), status="queued", stage="plan")
    await login(client, world.viewer)
    body = await dash(client)
    assert body["queued"]["total"] == 7 and len(body["queued"]["items"]) == 5
    assert body["numbers"]["runs_queued"] == 7

async def test_failed_runs_and_success_rate_over_24_hours(client, db, world):
    now = datetime.now(UTC)
    for status, ago in [("completed", 1), ("completed", 2), ("completed", 3), ("failed", 4), ("failed", 48),
                        ("cancelled", 5)]:
        await add_run(db, world.agent, task=await add_task(db, world.pay), status=status,
                      started_at=now - timedelta(hours=ago + 1), finished_at=now - timedelta(hours=ago))
    await add_run(db, world.other_agent, task=await add_task(db, world.web), status="failed", finished_at=now)
    await login(client, world.viewer)
    n = (await dash(client))["numbers"]
    assert (n["failed_24h"], n["success_rate_24h"]) == (1, 0.75)

def test_connected_count_skips_closed_connections():
    reg = RunnerRegistry()
    open_, closed = SimpleNamespace(closed=asyncio.Event()), SimpleNamespace(closed=asyncio.Event())
    closed.closed.set()
    reg._conns = {uuid.uuid4(): open_, uuid.uuid4(): closed}
    assert reg.connected_count() == 1
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/dashboard/test_agents.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** per the Rules. Statuses come from `agent_statuses(db, [(id, owner_id), ...])` in one call.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/dashboard -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(dashboard): agents, running and queued runs`.

### Task 5: Recent activity, System, and the speed check

**Files:**
- Create: `backend/app/dashboard/activity.py`, `backend/app/dashboard/system.py`
- Modify: `backend/app/dashboard/router.py` (fill `activity`; `system` for admins)
- Test:
  - `backend/tests/dashboard/test_activity.py`
  - `backend/tests/dashboard/test_system.py`
  - `backend/tests/dashboard/test_speed.py`

**Interfaces:**
- **Produces:**
  - `async def activity(db, scope, limit: int = 8) -> list[ActivityRow]`
  - `async def system(db) -> SystemOut`
  - `SEARCH_CACHE_SECONDS = 60`
  - `def reset_search_cache() -> None` (for tests)
- **Activity rules:**
  - `TaskEvent` rows of counted and uncounted tasks alike in scope (and `mine_tasks()` under `mine`), newest first.
  - Excluded kinds: `question.%` and the streamed agent kinds from Global Constraints.
  - `actor_name`: the user's name, else `data.agent_id`'s agent name, else None.
  - `names`: maps every id in `data` under the keys `to_column`, `from_column`, `to`, `from`, `to_agent` and `from_agent` to the column, user or agent name. This lets the frontend reuse `describeEvent`.
- **System rules:**
  - `runners`: `registry.connected_count()`.
  - `agents_exist`: any `Agent`.
  - `jobs_waiting` and `oldest_job_seconds`: jobs with status `queued` and `run_after <= now()`.
  - `search_available` and `search_documents`: as `/api/admin/search` computes them, cached in the module for 60 s (`time.monotonic`).
  - `ai_configured`: any `AiProvider`.
  - `ai_jobs_today` and `ai_failed_today`: `AiUsage` since `day_start(today())`, and those with `ok = false`.
  - `memory_last_at` and `memory_last_failed`: the newest `MemDreamRun` with `finished_at`, and whether its status is `failed`.
  - `rate_limits_24h`: `AuditLog.action == "rate_limit.blocked"` in the last 24 h.

- [ ] **Step 1: Write the failing tests**

```python
# test_activity.py
async def test_activity_is_the_eight_latest_task_events_without_streamed_updates(client, db, world):
    task = await add_task(db, world.pay)
    working = await column_id(db, world.pay, "working")
    for kind, data, actor in [("created", {}, world.viewer.id), ("status_changed", {"to_column": str(working)}, world.viewer.id),
                              ("agent_message", {"text": "hi"}, None), ("question.asked", {}, None),
                              ("agent_run_completed", {"agent_id": str(world.agent.id)}, None)]:
        db.add(TaskEvent(task_id=task.id, kind=kind, data=data, actor_user_id=actor))
        await db.commit()
    db.add(TaskEvent(task_id=(await add_task(db, world.web)).id, kind="created", data={})); await db.commit()
    await login(client, world.viewer)
    rows = (await dash(client))["activity"]
    assert [r["kind"] for r in rows] == ["agent_run_completed", "status_changed", "created"]
    assert rows[0]["actor_name"] == "Viewer bot" and rows[1]["actor_name"] == world.viewer.name
    assert rows[1]["names"] == {str(working): "In Progress"} and rows[1]["task_key"] == task_key(task)

async def test_activity_stops_at_eight(client, db, world):
    task = await add_task(db, world.pay)
    for _ in range(10):
        db.add(TaskEvent(task_id=task.id, kind="created", data={}))
    await db.commit()
    await login(client, world.viewer)
    assert len((await dash(client))["activity"]) == 8
```

The column name the test expects is whatever the default `working` column is called. Read it from `BoardColumn` in the test if it isn't "In Progress".

```python
# test_system.py
async def test_system_lines_for_admins(client, db, world, monkeypatch):
    now = datetime.now(UTC)
    db.add_all([Job(kind="x", run_after=now - timedelta(minutes=6)), Job(kind="x", run_after=now),
                Job(kind="x", run_after=now + timedelta(hours=1)),
                AuditLog(action="rate_limit.blocked", data={}), AuditLog(action="rate_limit.blocked", data={}),
                AuditLog(action="rate_limit.blocked", data={}, created_at=now - timedelta(days=2)),
                AiProvider(name="p", kind="openai"),
                AiUsage(job="embeddings", model="m", ok=True), AiUsage(job="embeddings", model="m", ok=False),
                MemDreamRun(trigger="schedule", status="failed", finished_at=now - timedelta(hours=1))])
    await db.commit()
    monkeypatch.setattr(registry, "connected_count", lambda: 2)
    calls = []
    async def health(): calls.append(1); return True
    async def count(): return 42
    monkeypatch.setattr(search_client, "health", health); monkeypatch.setattr(search_client, "document_count", count)
    reset_search_cache()
    await login(client, world.admin)
    s = (await dash(client, "all"))["system"]
    assert s["runners"] == 2 and s["agents_exist"] is True
    assert s["jobs_waiting"] == 2 and s["oldest_job_seconds"] >= 360
    assert (s["search_available"], s["search_documents"]) == (True, 42)
    assert (s["ai_configured"], s["ai_jobs_today"], s["ai_failed_today"]) == (True, 2, 1)
    assert s["memory_last_failed"] is True and s["rate_limits_24h"] == 2
    await dash(client, "all")
    assert len(calls) == 1                                                       # cached for 60 s

async def test_search_down_is_reported_not_raised(client, db, world, monkeypatch):
    async def health(): return False
    monkeypatch.setattr(search_client, "health", health); reset_search_cache()
    await login(client, world.admin)
    s = (await dash(client, "all"))["system"]
    assert (s["search_available"], s["search_documents"]) == (False, None)

# test_speed.py
async def test_dashboard_answers_under_300ms_with_10k_tasks(client, db, world):
    # 10,000 tasks across PAY's columns in one INSERT ... SELECT generate_series, a fifth done with completed_at in the
    # last 14 days, a tenth with a due date, some assigned to the viewer and to world.agent
    await db.execute(text(BULK_INSERT), {...}); await db.commit()
    await login(client, world.admin)
    timings = []
    for _ in range(3):
        start = time.perf_counter(); r = await client.get("/api/dashboard", params={"scope": "all"}); timings.append(time.perf_counter() - start)
        assert r.status_code == 200
    assert min(timings) < 0.3, timings
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/dashboard/test_activity.py tests/dashboard/test_system.py tests/dashboard/test_speed.py -q`
  - Expected: FAIL. The speed test may already pass; if it does, note that in the ledger.

- [ ] **Step 3: Implement.**
  - The activity query joins `TaskEvent → Task → Project`, filtered and limited in SQL.
  - Names come from one lookup per kind (columns, users, agents) over the 8 rows.
  - `system()` runs its counts as one `select` of scalar subqueries, plus the cached search check.
  - If the speed test fails, use `EXPLAIN ANALYZE` on the slow section and add the missing index in a migration against `megoo_migrate`. Do not cache.

- [ ] **Step 4: Run the tests.**
  - Run `uv run pytest tests/dashboard -q`. Expected: all pass.
  - Then run the whole suite once, in the background with output to the workspace (never two pytest processes at once): `uv run pytest -q -x`. Expected: green.

- [ ] **Step 5: Commit** `feat(dashboard): recent activity, system status and the speed check`.

### Task 6: Throttled live updates, dashboard queries, and the sidebar entry

**Files:**
- Modify:
  - `frontend/src/lib/realtime.ts`
  - `frontend/src/lib/api-types.ts` (`npm run gen:api`)
  - `frontend/src/components/shell/Sidebar.tsx`
  - `frontend/src/components/shell/__tests__/DesktopSidebar.test.tsx` (wrap in a `QueryClientProvider`, stub `fetch`)
- Create: `frontend/src/lib/dashboard.ts`
- Test:
  - `frontend/src/lib/__tests__/realtime.test.ts`
  - `frontend/src/lib/__tests__/dashboard.test.ts`
  - `frontend/src/components/shell/__tests__/Sidebar.test.tsx`

**Interfaces:**
- Consumes: the API schemas from Tasks 2–5, via `components["schemas"]`.
- **Produces, `realtime.ts`:**
  - `export const THROTTLE_MS = 2_000`
  - `export function throttledFor(event: LiveEvent): QueryKey[]`
  - `export function createThrottle(client: QueryClient, ms = THROTTLE_MS): { add(key: QueryKey): void; stop(): void }`:
    - The first `add` starts one timer.
    - When it fires, it invalidates every key added since, then clears.
    - `stop` cancels the timer.
  - `connectRealtime` uses one throttle; its close function calls `stop()`.
- **Produces, `dashboard.ts`:**
  - Types:
    - `type Dashboard = S["DashboardOut"]`
    - `type DashboardScope = "mine" | "teams" | "all"`
    - plus `NeedItem`, `RunningItem`, `AgentItem`, `StageRow`, `DayFinished`, `ProjectRow`, `ActivityRow`, `SystemOut`, `MyTask`, `Numbers`.
  - `dashboardKeys`:
    - `all: ["dashboard"]`
    - `scope: (s) => ["dashboard", s]`
    - `count: () => ["dashboard-count"]`
  - Hooks:
    - `useDashboard(scope: DashboardScope, isAdmin: boolean)`: `refetchInterval` is `60_000` for admins, otherwise `false`.
    - `useDashboardCount()`: `GET /api/dashboard/count`.
  - Scope memory:
    - `SCOPE_KEY = "megoo.dashboard.scope"`
    - `readScope(isAdmin: boolean): DashboardScope` returns `"teams"` when nothing valid is stored, or when `"all"` is stored for a non-admin.
    - `writeScope(s: DashboardScope): void`
  - Formatting and links:
    - `shortDuration(ms: number): string`: under 60 s → `"N s"`; under 60 min → `"N m"`; under 24 h → `"N h"`; else `"N d"`. Floors, minimum 0.
    - `taskLink(key: string): string` → `/projects/<part before the last "-">/board?task=<key>`.

- [ ] **Step 1: Write the failing tests.** Add to `realtime.test.ts`:

```ts
describe("dashboard throttle", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("maps events to the dashboard and the badge", () => {
    expect(throttledFor({ type: "task.updated" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "notification.created" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "question.updated" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "agents.changed" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "sprint.updated" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "project.updated" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "kb.changed" })).toEqual([]);
  });

  it("refetches once at the end of the window however many events arrive", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    vi.stubGlobal("WebSocket", MockSocket);
    connectRealtime(client);
    const socket = MockSocket.instances.at(-1)!;
    for (let i = 0; i < 50; i++) socket.emit({ type: "task.updated", project_id: "p1" });
    const dashboardCalls = () => spy.mock.calls.filter(([f]) => JSON.stringify(f?.queryKey) === '["dashboard"]').length;
    expect(dashboardCalls()).toBe(0);
    vi.advanceTimersByTime(THROTTLE_MS);
    expect(dashboardCalls()).toBe(1);
    socket.emit({ type: "agents.changed" });
    vi.advanceTimersByTime(THROTTLE_MS);
    expect(dashboardCalls()).toBe(2);
  });

  it("stops the pending refetch when closed", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    vi.stubGlobal("WebSocket", MockSocket);
    const close = connectRealtime(client);
    MockSocket.instances.at(-1)!.emit({ type: "task.updated" });
    close();
    vi.advanceTimersByTime(THROTTLE_MS * 2);
    expect(spy.mock.calls.some(([f]) => JSON.stringify(f?.queryKey) === '["dashboard"]')).toBe(false);
  });
});
```

`dashboard.test.ts`:

```ts
it("formats durations", () => {
  expect([shortDuration(42_000), shortDuration(12 * 60_000), shortDuration(5 * 3_600_000), shortDuration(2 * 86_400_000)])
    .toEqual(["42 s", "12 m", "5 h", "2 d"]);
});
it("links a task key to its board", () => expect(taskLink("PAY-12")).toBe("/projects/PAY/board?task=PAY-12"));
it("remembers the scope, and never offers Everything to a non-admin", () => {
  localStorage.clear();
  expect(readScope(false)).toBe("teams");
  writeScope("mine"); expect(readScope(false)).toBe("mine");
  writeScope("all"); expect(readScope(false)).toBe("teams"); expect(readScope(true)).toBe("all");
});
it("survives storage that throws", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(readScope(true)).toBe("teams");
});
```

`Sidebar.test.tsx`:

```ts
it("puts Dashboard first with the need-you badge", async () => {
  mockFetch((url) => (url === "/api/dashboard/count" ? json({ needs_you: 3 }) : undefined));
  wrap(<Sidebar user={member} />);
  const nav = within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link").slice(1); // [0] is the logo
  expect(nav[0]).toHaveAttribute("href", "/");
  expect(await within(nav[0]).findByLabelText("3 need you")).toHaveTextContent("3");
});
it("shows no badge at zero", async () => {
  const fetchMock = mockFetch((url) => (url === "/api/dashboard/count" ? json({ needs_you: 0 }) : undefined));
  wrap(<Sidebar user={member} />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/count", expect.anything()));
  expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();          // no badge in the name
});
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `cd frontend && npx vitest run src/lib src/components/shell`
  - Expected: FAIL (`throttledFor` and `lib/dashboard` are missing; no Dashboard link).

- [ ] **Step 3: Implement.**
  1. Run `npm run gen:api` first, so `S["DashboardOut"]` and the other schemas exist.
  2. In `connectRealtime`, after the existing invalidations: `for (const k of throttledFor(event)) throttle.add(k)`.
  3. Sidebar: `MAIN` starts with `{ href: "/", label: "Dashboard", icon: LayoutDashboard }`.
     - `NavLink` takes an optional `badge?: number`. It renders a pink pill like the bell's: `bg-pink text-on-accent`, `99+` cap, hidden at 0.
     - Expanded, the pill sits after the label (`ml-auto`). In the collapsed rail it sits on the icon's top-right corner.
     - The badge has `aria-label="<n> need you"`.
     - Only the Dashboard item uses `useDashboardCount()`.

- [ ] **Step 4: Run the tests.**
  - Run: `npx vitest run && npx tsc --noEmit && npm run lint`
  - Expected: all pass, clean.

- [ ] **Step 5: Commit** `feat(frontend): throttled live dashboard queries and the Dashboard sidebar entry`.

### Task 7: The dashboard page, scope switch, KPI tiles, Needs you, My tasks, Running now, Agents

**Files:**
- Modify:
  - `frontend/src/app/(app)/page.tsx` (render `<Dashboard />`)
  - landing paths: `src/app/(auth)/login/LoginForm.tsx` (`safeNext` fallback), `src/app/(auth)/setup/page.tsx`, `src/app/(auth)/invite/[token]/page.tsx`, `src/app/(auth)/change-password/page.tsx`
  - `src/app/manifest.ts` (`start_url`), `src/components/shell/Sidebar.tsx` (logo → `/`)
  - their tests, plus `e2e/helpers/auth.ts:20`, `e2e/foundation.spec.ts:79` and `e2e/pwa.spec.ts:35`: expect `/` where they follow a sign-in, setup or invite (`toHaveURL(/\/$/)`)
- Create, in `frontend/src/components/dashboard/`:
  - `Dashboard.tsx`
  - `Widget.tsx`
  - `ScopeSwitch.tsx`
  - `Kpis.tsx`
  - `NeedsYou.tsx`
  - `MyTasks.tsx`
  - `RunningNow.tsx`
  - `AgentsCard.tsx`
- Test, in `frontend/src/components/dashboard/__tests__/`:
  - `fixture.ts`: `export function dashboardFixture(over?: Partial<Dashboard>): Dashboard` with realistic values for every section.
  - `Dashboard.test.tsx`
  - `Kpis.test.tsx`
  - `NeedsYou.test.tsx`
  - `MyTasks.test.tsx`
  - `RunningNow.test.tsx`
  - `AgentsCard.test.tsx`

**Interfaces:**
- Consumes: `lib/dashboard.ts` (Task 6), `escalationReasonText` and `STAGES` from `lib/workflow`, `useMe`.
- **Produces:**
  - `Widget({ title, icon, more?: { href, label }, count?: number, loading?: boolean, children })`: the card frame. While `loading`, it shows a muted placeholder block of fixed height.
  - Widgets that take their data as props:
    - `Kpis({ numbers })`
    - `NeedsYou({ items, total, showWaitingFor })`
    - `MyTasks({ items })`
    - `RunningNow({ running, queued, isAdmin })`
    - `AgentsCard({ agents, isAdmin })`
  - `Dashboard()`: owns scope, the query and the layout. Task 8 adds the remaining widgets into the same layout.
- **Copy:**
  - Need labels:
    - `design_approval` "Approve design", `plan_approval` "Approve plan" (amber);
    - `question` "Agent asks" (cyan);
    - `escalation` "Stuck" (pink);
    - `human_code_review` "Code review" (violet, or cyan until Task 8 adds the token);
    - `draft_answer` "Question to send" (cyan);
    - `needs_human` "Question needs a person" (amber);
    - `mention` "Mention" (muted).
  - Buttons: Review / Review / Answer / Look / Review / Check / Answer / Reply.
  - Summary line per kind:
    - `title`;
    - for `question` "“<detail>”";
    - for `escalation` `escalationReasonText(detail)`;
    - for `human_code_review` "Pull request · <title>";
    - for `mention` "<title>: “<detail>”".
  - Under My teams and Everything, each need row adds a second muted line, "waits for A, B".
  - KPI labels exactly:
    - "Need you" (small: "N over a day old")
    - "Agents working / online" (small: "N runs queued")
    - "Workflows in progress" (small: "across N projects")
    - "Open tasks" (small: "N in progress")
    - "Done, last 7 days" (small: "▲ N on the 7 days before", "▼ N on the 7 days before", or "same as the 7 days before")
    - "Overdue" (small: "N assigned to you")
    - "Failed runs, 24 h" (small: "N% succeeded", or "no runs finished")
  - Scope buttons: "Mine", "My teams", "Everything" (admins only). This is a radio group named "Scope"; each option has `aria-pressed`.
  - Page heading "Dashboard", with the subtitle "Updates live".

- [ ] **Step 1: Write the failing tests** (key cases; each widget file also covers its empty state from Global Constraints):

```tsx
// Dashboard.test.tsx — fetch stubbed to return dashboardFixture() for /api/dashboard?scope=…, useMe mocked
it("asks for My teams by default and remembers a new choice", async () => {
  const fetchMock = mockFetch(...);
  wrap(<Dashboard />);
  await screen.findByText("Need you");
  expect(urls(fetchMock)).toContain("/api/dashboard?scope=teams");
  await user.click(screen.getByRole("button", { name: "Mine" }));
  await waitFor(() => expect(urls(fetchMock)).toContain("/api/dashboard?scope=mine"));
  expect(localStorage.getItem(SCOPE_KEY)).toBe("mine");
});
it("offers Everything to admins only", ...);           // member: queryByRole("button", {name: "Everything"}) is null
it("refetches every 60 s for admins only", ...);       // fake timers: admin → 2 dashboard fetches after 60 s; member → 1

// Kpis.test.tsx
it("draws Need you and Overdue in pink when above zero", () => {
  render(<Kpis numbers={{ ...numbers, need_you: 3, need_you_over_day: 1, overdue: 0 }} />);
  expect(tile("Need you")).toHaveAttribute("data-alert", "true");
  expect(tile("Overdue")).toHaveAttribute("data-alert", "false");
  expect(screen.getByText("1 over a day old")).toBeInTheDocument();
});
it("shows the success rate, or that no runs finished", ...);  // 0.75 → "75% succeeded"; null → "no runs finished"

// NeedsYou.test.tsx
it("labels each row and links it to the task", () => {
  render(<NeedsYou items={[need("design_approval", "PAY-12", "Refund flow")]} total={1} showWaitingFor={false} />);
  expect(screen.getByText("Approve design")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review PAY-12" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-12");
});
it("Reply marks the mention read, refetches at once, then opens the task", async () => {
  // POST /api/notifications/n1/read is called before router.push(link); invalidateQueries called with
  // {queryKey: ["dashboard"]} and {queryKey: ["dashboard-count"]}
});
it("names who each row waits for under My teams", ...);     // showWaitingFor → "waits for Ana, Omar"
it("says when nothing needs you", ...);                     // "Nothing needs you."

// MyTasks.test.tsx
it("labels Overdue, Today and This week", ...);

// RunningNow.test.tsx
it("ticks the elapsed time without refetching", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-28T10:12:00Z"));
  render(<RunningNow running={[run({ started_at: "2026-10-28T10:00:00Z" })]} queued={{ total: 0, items: [] }} isAdmin={false} />);
  expect(screen.getByText("12 m")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(60_000));
  expect(screen.getByText("13 m")).toBeInTheDocument();
});
it("shows Build progress and answering runs", ...);  // "Step 2 of 3"; "Answering a question from WEB" links to /questions/<id>
it("lists five queued keys then the rest as a number", ...);  // "Queued: PAY-16 Plan · WEB-33 Design … and 2 more"
it("links All runs to the admin page for admins and My agents for others", ...);

// AgentsCard.test.tsx
it("labels Working, Idle and Offline with runs today", ...);  // busy→"Working", online→"Idle", offline→"Offline"; "9 runs today", "1 run today"
```

Write each `...` case in full, with the assertions named in its comment.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `npx vitest run src/components/dashboard "src/app"`
  - Expected: FAIL (missing modules; the landing tests still expect `/projects`).

- [ ] **Step 3: Implement.**
  - **Layout (A):** `Kpis` across the top. Below it, `grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]` holds two stacks: [NeedsYou, MyTasks] and [RunningNow, AgentsCard].
  - **Rows:** `flex min-w-0 items-center gap-2`, with the text part `min-w-0 flex-1 truncate`.
  - **Ticking:** `RunningNow` keeps a `now` state updated by `setInterval(…, 1000)`, cleared on unmount.
  - **Reply:** `api(\`/api/notifications/${id}/read\`, { method: "POST" })`. Then invalidate both dashboard keys directly (no throttle), then `router.push(link)`.
  - **Other buttons** are `Link`s with the label as visible text, and `aria-label="<Button> <ref>"`.
  - **Landing:** change the `"/projects"` fallbacks named in Files to `"/"`.

- [ ] **Step 4: Run the tests.**
  - Run: `npx vitest run && npx tsc --noEmit && npm run lint`
  - Expected: all pass, clean.

- [ ] **Step 5: Commit** `feat(frontend): dashboard home with needs you, my tasks, running runs and agents`.

### Task 8: Workflows by stage, Tasks finished, Projects, Recent activity, System

**Files:**
- Modify:
  - `frontend/src/app/globals.css` (add `--violet`: light `#6d28d9`, dark `#b18cff`; and `--color-violet`)
  - `frontend/src/components/dashboard/Dashboard.tsx` (second grid and System)
  - `frontend/src/components/dashboard/NeedsYou.tsx` (Code review → violet)
- Create, in `frontend/src/components/dashboard/`:
  - `StageBars.tsx`
  - `FinishedChart.tsx`
  - `ProjectsCard.tsx`
  - `RecentActivity.tsx`
  - `SystemCard.tsx`
- Test, in `frontend/src/components/dashboard/__tests__/`:
  - `StageBars.test.tsx`
  - `FinishedChart.test.tsx`
  - `ProjectsCard.test.tsx`
  - `RecentActivity.test.tsx`
  - `SystemCard.test.tsx`

**Interfaces:**
- Consumes: `Widget`, the fixture, `describeEvent` from `components/task/ActivityThread`, and `STAGES`.
- **Produces:**
  - `StageBars({ stages })`
  - `FinishedChart({ days })`
  - `ProjectsCard({ projects })`
  - `RecentActivity({ rows })`
  - `SystemCard({ system })`
  - `export function systemLines(s: SystemOut, now: Date): { label: string; value: string; attention: boolean }[]`, returning six lines in spec order.
- **Rules:**
  - **Stage labels:** Brainstorm, Design, Plan, Build, Review, Finishing (for `done`), and a final "Done" row.
  - **Segment widths:** a percentage of the largest stage total (running + waiting + paused). Done is always 100% green with its number.
  - **Legend:** "agent working", "waiting for a person", "paused or manual", "finished in the last 30 days".
  - **Chart:** 14 columns, each with cyan (agents) and violet (people) segments. Column height is a percentage of the largest day total.
    - Axis: the first, middle (index 7) and last day, formatted `d MMM` with `toLocaleDateString(undefined, { day: "numeric", month: "short" })`.
    - Legend: "by agents · N", "by people · N".
    - The chart has `role="img"` and `aria-label="Tasks finished in the last 14 days: N by agents, M by people"`.
  - **Projects:** progress bar with done in green and `in_progress` in cyan, as fractions of open + done. The row reads "N open", plus " · N late" in pink when above 0.
  - **Activity:** the text is `describeEvent(kind, data, { columnNames, userNames, agentNames })`, with all three maps built from `row.names`. The line reads "<actor_name ?? 'MegooColab'> <text> · <KEY-n>", with the key linked.
  - **System attention:**
    - runners 0 while `agents_exist`;
    - `jobs_waiting > 50`, or `oldest_job_seconds > 300`;
    - `!search_available`;
    - `!ai_configured`, or `ai_failed_today > 0`;
    - `memory_last_failed`, or no run (or the last run) older than 26 h;
    - `rate_limits_24h > 0`.
  - **System values:**
    - "N connected"
    - "N waiting"
    - "Available · N items" / "Unavailable"
    - "OK · N jobs today" / "Not configured"
    - "last learned HH:MM" / "never"
    - "N in 24 h"

- [ ] **Step 1: Write the failing tests** (key cases; each also covers its empty state):

```tsx
it("splits each stage bar into working, waiting and paused, scaled to the largest", () => {
  render(<StageBars stages={{ rows: [row("build", 2, 1, 1), row("plan", 0, 2, 0), ...zeros], done_30d: 31 }} />);
  const build = screen.getByRole("group", { name: "Build" });
  expect(segments(build)).toEqual(["50%", "25%", "25%"]);            // style widths
  expect(segments(screen.getByRole("group", { name: "Plan" }))).toEqual(["0%", "50%", "0%"]);
  expect(within(screen.getByRole("group", { name: "Done" })).getByText("31")).toBeInTheDocument();
});

it("draws 14 stacked days with first, middle and last labels and totals", () => {
  render(<FinishedChart days={fourteenDays({ last: { agents: 2, people: 1 } })} />);
  expect(screen.getByRole("img")).toHaveAccessibleName(/2 by agents, 1 by people/);
  expect(screen.getByText("by agents · 2")).toBeInTheDocument();
});

it("words activity like the task's own list", () => {
  render(<RecentActivity rows={[{ ...act, kind: "status_changed", data: { to_column: "c1" }, names: { c1: "In Progress" }, actor_name: "Ana", task_key: "PAY-3" }]} />);
  expect(screen.getByText(/Ana moved this to In Progress/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "PAY-3" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-3");
});

it.each([
  ["no runner while agents exist", { runners: 0, agents_exist: true }, "Runners connected"],
  ["51 jobs waiting", { jobs_waiting: 51 }, "Background jobs"],
  ["the oldest job waited 301 s", { oldest_job_seconds: 301 }, "Background jobs"],
  ["search down", { search_available: false }, "Search index"],
  ["an AI job failed", { ai_failed_today: 1 }, "AI provider"],
  ["memory last ran 27 h ago", { memory_last_at: hoursAgo(27) }, "Memory"],
  ["a rate limit was hit", { rate_limits_24h: 1 }, "Rate limits hit"],
])("needs attention when %s", (_, over, label) => {
  const lines = systemLines({ ...healthy, ...over }, NOW);
  expect(lines.filter((l) => l.attention).map((l) => l.label)).toEqual([label]);
});
it("is all green when healthy", () => expect(systemLines(healthy, NOW).every((l) => !l.attention)).toBe(true));
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `npx vitest run src/components/dashboard`
  - Expected: FAIL (missing modules).

- [ ] **Step 3: Implement.**
  - **Layout:** below the Task 7 grid, `grid gap-3 lg:grid-cols-2` holds StageBars, FinishedChart, ProjectsCard and RecentActivity. After it, `SystemCard` spans the full width, rendered only when `data.system` is non-null.
  - **System grid:** `sm:grid-cols-2`.
  - **Heading:** an amber "admins only" tag next to the System heading.
  - **Loading:** every widget renders through `Widget loading` while the query has no data, so the layout does not jump.

- [ ] **Step 4: Run the tests.**
  - Run: `npx vitest run && npx tsc --noEmit && npm run lint`
  - Expected: all pass, clean.

- [ ] **Step 5: Commit** `feat(frontend): workflow stages, finished chart, projects, activity and system on the dashboard`.

### Task 9: End-to-end: live row and badge, and the phone check

**Files:**
- Create:
  - `frontend/e2e/helpers/mcp.ts`: move `tool()` out of `kb.spec.ts`, and import it there.
  - `frontend/e2e/dashboard.spec.ts`
- Modify: `frontend/e2e/mobile.spec.ts` (add `"/"` to `pages`, after setting up a long-titled waiting task)

**Interfaces:**
- Consumes: `setupOrSignIn`, `ADMIN` and `tool(request, token, name, args)`.

- [ ] **Step 1: Write the spec** `dashboard.spec.ts` ("dashboard: a design waiting for approval shows up live"):
  1. **Set up through the API:**
     - `setupOrSignIn(page)`.
     - Create team "Dash Team" and add the admin to it (`PUT /api/teams/<id>/members`).
     - Create project `DSH` on that team.
     - Create task "Design the dashboard copy", `assignee_user_id` = the admin.
     - Create a personal token with scope `mcp`.
  2. **Read the baseline:** `page.goto("/")`. Expect heading "Dashboard", and read the "Need you" tile's number (`n`).
  3. **Make the design wait:** `tool(request, token, "submit_design", { key, markdown: "# Copy\n\nShort words." })`. The workflow is connect-only; it now waits for a design approval addressed to the admin.
  4. **Assert without reloading:**
     - The Needs you list shows a row with "Approve design" and the task key within 10 s.
     - The "Need you" tile reads `n + 1`.
     - The sidebar's Dashboard link has a badge `≥ 1`, named "<count> need you".
     - Clicking the row's "Review <key>" lands on `/projects/DSH/board?task=<key>`.

  In `mobile.spec.ts`:
  - Before the page loop, create a waiting task in MOB whose title is 120 characters long (the same `submit_design` route, with a token).
  - Add `"/"` to `pages`.

- [ ] **Step 2: Run it against a fresh stack.**
  ```
  MSYS_NO_PATHCONV=1 docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env down -v
  MSYS_NO_PATHCONV=1 docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env up -d --build --wait
  cd frontend && npx playwright test dashboard.spec.ts mobile.spec.ts
  ```
  - Expected: both pass. A failure here is a finding: debug it with superpowers:systematic-debugging, not by loosening the test.

- [ ] **Step 3: Run the whole e2e suite** on a fresh stack (same `down -v` / `up` commands, then `npx playwright test`).
  - Expected: 20/20 (19 existing + dashboard).
  - The landing change from Task 7 is exercised here by `helpers/auth.ts`, `foundation.spec.ts` and `pwa.spec.ts`.

- [ ] **Step 4: Commit** `test(e2e): the dashboard updates live and fits a phone`.
