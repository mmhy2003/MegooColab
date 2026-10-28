# Project Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete sprints (tasks back to the backlog), delete projects from Settings (admins, typed key, nothing left behind), and give projects an Active / Finished / Archived status that makes closed projects read-only, stops their work, and drops them from the dashboard, search and question targets as the spec's table says.

**Architecture:**
- **One closed-project check.** `projects.status` (a string, default `active`) is checked inside the existing write gate `get_project_for(..., write=True)`, so every board, task, sprint, settings and MCP write is refused with 409 `project_closed`.
- **Explicit exemptions.** The status route and the delete route load the project without `write=True` and check roles themselves. The question-answering path never used the write gate.
- **Closing a project** pauses its active workflows through the engine's own `pause`.
- **Upload folders** of deleted tasks are removed by a session `after_commit` hook, so a failed delete keeps its files.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, pytest; Next 16 / React 19 / TanStack Query 5 / Tailwind 4, Vitest + Testing Library; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-29-project-lifecycle-design.md` (including "Settled after the builder check").

## Global Constraints

- **Statuses:** `active`, `finished` and `archived`, in a `ProjectStatus` StrEnum in `app/projects/models.py`. New and existing projects are `active`.
- **Refused writes:** 409 with detail `project_closed`. Frontend message for it: "This project is closed. Reopen it to make changes."
- **Exempt from the closed check:**
  - `PUT /api/projects/{ref}/status`
  - `DELETE /api/projects/{ref}`
  - `GET /api/projects/{ref}/workflows-in-progress`
  - the question-answering path: routing, answering runs and their MCP tools, approving or rejecting a draft, and a person answering
- **Who can do what:**
  - Change status: `require_manage` (the project's managers and admins).
  - Delete a project: admins only, in any status.
  - Delete a sprint: `require_manage`, and only in an Active project.
- **Audit actions:**
  - `sprint.deleted`, with `{"name": ...}`.
  - `project.status_changed`, with `{"from": ..., "to": ...}`.
  - `project.deleted` (existing).
- **Live events:** a status change publishes `project.updated`; a sprint delete publishes `sprint.updated`.
- **Banner copy:**
  - "This project is finished. It is read-only." with the button **Reopen**.
  - "This project is archived. It is read-only and hidden from lists." with the button **Restore**.
  - Only people who may change status see the buttons.
- **Remembered "Show archived" choice:** `localStorage["megoo.projects.showArchived"]`, read and written inside try/catch.
- **Generating migrations:** only against `megoo_migrate` (`DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate bash scripts/makemigration.sh "<msg>"`).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Plan rulings** (cost if wrong in brackets):
  - A completed sprint is deleted from the Reports page, next to its sprint picker. The Backlog page only lists planned and active sprints. [one button's place]
  - A person on a deleted project's page sees the project layout's existing "That project doesn't exist" card with "Back to projects", rather than being redirected away automatically. [one redirect]
  - The 409 message is one sentence for both closed states; the banner says which state it is. [copy]

## Review Focus

1. **Closing a project while an agent is mid-run.** The run is cancelled and the workflow paused. The runner's late `run_finished` or progress for that run must not reopen work or fail. Test: Task 2, `test_closing_pauses_workflows_and_cancels_runs`.
2. **A manager reopens a project they can no longer write to.** The status route works on a closed project, while every other route still refuses. Test: Task 2, `test_status_route_reopens_a_closed_project`.
3. **Deleting a project whose delete fails halfway** (for example a database error): its upload folders are still on disk. Test: Task 3, `test_upload_folders_survive_a_rolled_back_delete`.
4. **An archived project's question that was already sent.** A person can still answer it, but no new question can be asked of the project. Test: Task 4, `test_archived_project_keeps_answering_but_takes_no_new_questions`.
5. **A finished project's task in My tasks or Needs you.** It disappears from the dashboard, while a direct link to the task still opens it read-only. Test: Task 4, `test_dashboard_counts_active_projects_only`.

---

### Task 1: Project status and the closed-project write check

**Files:**
- Modify:
  - `backend/app/projects/models.py` (`ProjectStatus`, `Project.status`)
  - `backend/app/projects/schemas.py` (`ProjectOut.status`)
  - `backend/app/projects/service.py` (`project_out`)
  - `backend/app/projects/access.py` (`get_project_for`)
- Create: a migration ("project status")
- Test: `backend/tests/projects/test_project_status.py`

**Interfaces:**
- Produces:
  - `ProjectStatus(StrEnum)`: `active`, `finished`, `archived`.
  - `Project.status: Mapped[ProjectStatus]`, a `String(20)` column with `server_default="active"`.
  - `ProjectOut.status: ProjectStatus`.
  - `get_project_for(..., write=True)` raises `HTTPException(409, "project_closed")` when `project.status != active`. This comes after the 404 and viewer checks, so outsiders still get 404.
  - Test helper `close(db, project_key, status)`, defined in `tests/projects/test_project_status.py` and imported by later tasks. It sets the column directly.

- [ ] **Step 1: Write the failing tests**

```python
async def test_new_projects_are_active(client, db):
    p, _m, _t = await make_project(client, db, "PAY")
    assert p["status"] == "active"

@pytest.mark.parametrize("status", ["finished", "archived"])
async def test_closed_projects_refuse_writes_and_allow_reads(client, db, status):
    _p, manager, _t = await make_project(client, db, "PAY")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    await close(db, "PAY", status)
    writes = [
        client.post("/api/projects/PAY/tasks", json={"title": "B"}),
        client.patch(f"/api/tasks/{task['key']}", json={"title": "C"}),
        client.post(f"/api/tasks/{task['key']}/comments", json={"body_md": "hi"}),
        client.post("/api/projects/PAY/sprints", json={"name": "S", "start_date": "2026-11-02", "end_date": "2026-11-13"}),
        client.post("/api/projects/PAY/labels", json={"name": "x", "color": "#ff0000"}),
        client.patch("/api/projects/PAY", json={"name": "Renamed"}),
        client.post(f"/api/tasks/{task['key']}/workflow/start"),
    ]
    for coro in writes:
        r = await coro
        assert (r.status_code, r.json()["detail"]) == (409, "project_closed"), r.text
    assert (await client.get("/api/projects/PAY")).json()["status"] == status
    assert (await client.get(f"/api/tasks/{task['key']}")).status_code == 200
    assert (await client.get("/api/projects/PAY/tasks")).status_code == 200

async def test_outsiders_still_get_404_on_a_closed_project(client, db):
    await make_project(client, db, "PAY")
    await close(db, "PAY", "finished")
    outsider = await make_user(db)
    await login(client, outsider)
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 404

async def test_mcp_writes_are_refused_on_a_closed_project(app, client, db, mcp_running):
    # as tests/mcp/test_mcp.py does: mint a token, open a session, call move_task on a finished project
    ...  # assert the tool returns an error whose text contains "project_closed"
```

Write the MCP case in full, following `test_create_and_move_task_via_mcp_publishes_events` (`_mint`, `mcp_session`, `call`).

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `cd backend && uv run pytest tests/projects/test_project_status.py -q`
  - Expected: FAIL (`status` missing from the response; writes succeed).

- [ ] **Step 3: Implement.**
  - Add the column and generate the migration against `megoo_migrate`. The server default backfills existing rows. Check `downgrade -1` and `upgrade head`.
  - Add the check to `get_project_for`.
  - Audit the writers: run `grep -rn "write=True\|get_task_for\|get_project_for" app` and confirm every write a person or agent makes to tasks, sprints and settings passes `write=True`. Route any that doesn't through it.
  - The question-answering path stays as it is; Task 4 tests it.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/projects tests/mcp tests/core/test_migrations.py -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(projects): project status, and closed projects refuse writes`.

### Task 2: Changing status, and closing stops the work

**Files:**
- Modify:
  - `backend/app/projects/router.py` (status route, count route; the delete route stops using `write=True`)
  - `backend/app/projects/schemas.py` (`ProjectStatusIn`, `WorkflowCountOut`)
- Create: `backend/app/projects/lifecycle.py`
- Test: `backend/tests/projects/test_project_status_route.py`

**Interfaces:**
- Consumes: `ProjectStatus` and `close()` (Task 1); `engine.pause(db, user, task)` and `engine.ACTIVE`.
- Produces:
  - `PUT /api/projects/{ref}/status`, body `ProjectStatusIn {status: ProjectStatus}`, returns `ProjectOut`. The project is loaded with `get_project_for(db, user, ref)` (no `write`), then `require_manage`; a viewer gets 403.
  - `GET /api/projects/{ref}/workflows-in-progress` returns `WorkflowCountOut {count: int}`.
  - In `lifecycle.py`:
    - `async def active_workflow_tasks(db, project_id) -> list[Task]`: tasks whose workflow has a status in `engine.ACTIVE` and a driver other than `manual`.
    - `async def set_status(db, user, project, status) -> None`: when leaving `active`, it pauses each of those tasks via `engine.pause(db, user, task)`, then sets the status, records `project.status_changed` and publishes `project.updated`.
  - Setting the same status again returns 200 and changes nothing.

- [ ] **Step 1: Write the failing tests**

```python
async def test_status_route_reopens_a_closed_project(client, db):
    await make_project(client, db, "PAY")                       # logged in as its manager
    r = await client.put("/api/projects/PAY/status", json={"status": "finished"})
    assert r.status_code == 200 and r.json()["status"] == "finished"
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 409
    r = await client.put("/api/projects/PAY/status", json={"status": "active"})
    assert r.json()["status"] == "active"
    assert (await client.post("/api/projects/PAY/tasks", json={"title": "B"})).status_code == 201
    rows = await audit_rows(db, "project.status_changed")
    assert [r.data for r in rows] == [{"from": "active", "to": "finished"}, {"from": "finished", "to": "active"}]

async def test_only_managers_and_admins_change_status(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    await login(client, member)
    assert (await client.put("/api/projects/PAY/status", json={"status": "archived"})).status_code == 403

async def test_closing_pauses_workflows_and_cancels_runs(db, tc_factory):
    # reuse tests/workflow/test_engine.py::_started: a runner-driven workflow with a running run on PAY
    tc = tc_factory(lifespan=True)
    board = await _started(db, tc)
    assert tc.get("/api/projects/PAY/workflows-in-progress").json() == {"count": 1}
    assert tc.put("/api/projects/PAY/status", json={"status": "finished"}).status_code == 200
    wf = tc.get(f"/api/tasks/{board.key}/workflow").json()
    assert wf["status"] == "paused"
    assert latest_run(db, board.key).status == "cancelled"     # helper from the workflow tests
    # the runner's late report for the cancelled run is ignored, nothing reopens
    finish_run_as_runner(tc, board)                             # as test_engine does for a finished run
    assert tc.get(f"/api/tasks/{board.key}/workflow").json()["status"] == "paused"
    assert tc.put("/api/projects/PAY/status", json={"status": "active"}).status_code == 200
    assert tc.get(f"/api/tasks/{board.key}/workflow").json()["status"] == "paused"   # reopening leaves it paused
```

Use the existing workflow-test helpers for `_started`, the latest run and the runner's `run_finished`. Their names are in `tests/workflow/test_engine.py` and `tests/runner/test_runner_ws.py`. If one does not exist under that name, compose it from what those files do.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/projects/test_project_status_route.py -q`
  - Expected: FAIL (404 or 405 on the new routes).

- [ ] **Step 3: Implement** per the Interfaces.
  - Lock order: pause one task at a time, in `task.id` order (`engine.pause` takes the task and workflow locks itself).
  - `delete_project` switches to `get_project_for(db, user, ref)` and keeps its admin check, so it works in any status.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/projects tests/workflow -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat(projects): change a project's status; closing pauses its workflows`.

### Task 3: Deleting sprints and projects, with nothing left behind

**Files:**
- Modify:
  - `backend/app/sprints/router.py` (`DELETE /api/sprints/{id}`)
  - `backend/app/projects/router.py` (`delete_project`)
  - `backend/app/tasks/router.py` (`delete_task`)
- Create: `backend/app/tasks/uploads.py`
- Test:
  - `backend/tests/sprints/test_sprint_delete.py`
  - `backend/tests/projects/test_project_delete.py`

**Interfaces:**
- Consumes: `close()` (Task 1); `service.deleted_with(task)`; `memory.sources.queue_forget(db)`; `search` purge (already wired for projects).
- Produces:
  - `DELETE /api/sprints/{sprint_id}` returns 204, using `_sprint_for(..., manage=True)`. Because that check uses the project write gate, it gives 409 on closed projects. It records `sprint.deleted` and publishes `sprint.updated`.
  - `uploads.remove_after_commit(db: AsyncSession, task_ids: Iterable[uuid.UUID]) -> None` records `<upload root>/<task id>` folders in `db.sync_session.info`. A module-level `Session` `after_commit` listener runs `shutil.rmtree(path, ignore_errors=True)` on each folder; `after_rollback` drops the list. The listener is registered on import, the same way `app/search/capture.py` registers its hook.
  - `delete_project` collects `select(Task.id).where(Task.project_id == project.id)`, calls `remove_after_commit` with them, and calls `queue_forget(db)`.
  - `delete_task` calls `remove_after_commit` with the ids from `service.deleted_with(task)`, before it deletes.

- [ ] **Step 1: Write the failing tests**

```python
# test_sprint_delete.py
async def test_deleting_a_sprint_returns_its_tasks_to_the_backlog(client, db):
    await make_project(client, db, "PAY")
    sprint = (await client.post("/api/projects/PAY/sprints", json={"name": "S1", "start_date": "2026-11-02", "end_date": "2026-11-13"})).json()
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    await client.put(f"/api/tasks/{task['key']}/sprint", json={"sprint_id": sprint["id"]})
    await client.post(f"/api/sprints/{sprint['id']}/start")
    assert (await client.delete(f"/api/sprints/{sprint['id']}")).status_code == 204
    assert (await client.get(f"/api/tasks/{task['key']}")).json()["sprint_id"] is None
    assert (await client.get("/api/projects/PAY/sprints")).json() == []
    assert await db.scalar(select(func.count()).select_from(SprintSnapshot)) == 0
    assert [r.data for r in await audit_rows(db, "sprint.deleted")] == [{"name": "S1"}]

async def test_members_cannot_delete_sprints_and_closed_projects_refuse(client, db):
    member = await make_user(db)
    await make_project(client, db, "PAY", member)
    sprint = (await client.post("/api/projects/PAY/sprints", json={"name": "S1", "start_date": "2026-11-02", "end_date": "2026-11-13"})).json()
    await login(client, member)
    assert (await client.delete(f"/api/sprints/{sprint['id']}")).status_code == 403
    await close(db, "PAY", "finished")
    await login(client, admin := await make_user(db, role=Role.admin))
    assert (await client.delete(f"/api/sprints/{sprint['id']}")).status_code == 409

# test_project_delete.py
async def test_admin_deletes_a_closed_project_with_everything(client, db, tmp_upload_root):
    await make_project(client, db, "PAY")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    await client.post(f"/api/tasks/{task['key']}/attachments", files={"file": ("a.txt", b"hi")})
    folder = tmp_upload_root / task["id"]
    assert folder.is_dir()
    await close(db, "PAY", "archived")
    await login(client, await make_user(db, role=Role.admin))
    assert (await client.delete("/api/projects/PAY")).status_code == 204
    assert not folder.exists()
    assert await db.scalar(select(func.count()).select_from(Task)) == 0
    assert await db.scalar(select(func.count()).select_from(Job).where(Job.kind == "mem.forget")) == 1

async def test_managers_cannot_delete_projects(client, db):
    await make_project(client, db, "PAY")                        # logged in as its manager
    assert (await client.delete("/api/projects/PAY")).status_code == 403

async def test_deleting_a_task_removes_its_and_its_subtasks_folders(client, db, tmp_upload_root):
    ...  # a task with a subtask, an attachment on each; delete the parent; both folders gone

async def test_upload_folders_survive_a_rolled_back_delete(db, tmp_upload_root):
    # call remove_after_commit for a task's id inside a session, then roll back: the folder is still there
    ...
```

`tmp_upload_root` is a fixture in `backend/tests/conftest.py` that yields `Path(get_settings().upload_dir)` (the suite already points `UPLOAD_DIR` at a temporary folder). Write the `...` cases in full as described in their comments.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/sprints/test_sprint_delete.py tests/projects/test_project_delete.py -q`
  - Expected: FAIL (405 on the sprint delete; the folder is still on disk; no `mem.forget` job).

- [ ] **Step 3: Implement** per the Interfaces.
  - Sprint delete: `await db.delete(sprint)`. The `ON DELETE SET NULL` foreign key on `tasks.sprint_id` and the snapshot cascade do the rest.

- [ ] **Step 4: Run the tests.**
  - Run: `uv run pytest tests/sprints tests/projects tests/tasks -q`
  - Expected: all pass.

- [ ] **Step 5: Commit** `feat: delete sprints and projects without leaving files behind`.

### Task 4: Closed projects leave the dashboard, search and the question targets

**Files:**
- Modify:
  - `backend/app/dashboard/scope.py` (`resolve_scope`)
  - `backend/app/dashboard/tasks.py` (`my_tasks`)
  - `backend/app/search/service.py` (`build_filter` callers)
  - `backend/app/a2a/router.py` (`targets`)
  - `backend/app/a2a/service.py` (`ask`)
- Test:
  - `backend/tests/projects/test_closed_elsewhere.py`
  - extend `backend/tests/search/` with one test (the file that holds the search filter tests)

**Interfaces:**
- Consumes: `ProjectStatus` and `close()` (Task 1).
- Produces:
  - `Scope.project_ids` holds Active projects only, in every scope (`all` becomes the set of Active project ids, no longer `None`).
  - `my_tasks` filters on `Project.status == active`.
  - Search adds `NOT (kind = "task" AND project_id IN [<archived ids>])` to the base filter when any project is archived (`archived_filter(ids: list[str]) -> str | None`). Knowledge Base documents are untouched.
  - `GET /api/questions/targets` lists only non-archived projects.
  - `ask` raises 409 `project_closed` when the target is archived.

- [ ] **Step 1: Write the failing tests**

```python
async def test_dashboard_counts_active_projects_only(client, db, world):
    # reuse tests/dashboard/conftest.py's world and helpers
    t = await add_task(db, world.pay, user=world.viewer, due=today())
    await add_workflow(db, await add_task(db, world.pay, user=world.viewer), stage="design",
                       status="waiting_human", needs="design_approval")
    await close(db, "PAY", "finished")
    await login(client, world.viewer)
    body = await dash(client, "mine")
    assert body["my_tasks"] == [] and body["needs"] == [] and body["projects"] == []
    assert (await client.get(f"/api/tasks/{task_key(t)}")).status_code == 200   # still opens, read-only

async def test_archived_project_keeps_answering_but_takes_no_new_questions(client, db, world):
    q = await add_question(db, world.pay, status="needs_human")
    await close(db, "PAY", "archived")
    await login(client, world.viewer)
    r = await client.post(f"/api/questions/{q.id}/answer", json={"answer_md": "Ops owns it."})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    assert "PAY" not in [t["key"] for t in (await client.get("/api/questions/targets")).json()]
    await login(client, world.other)
    r = await client.post("/api/questions", json={"project_key": "PAY", "body": "Who owns billing?"})
    assert (r.status_code, r.json()["detail"]) == (409, "project_closed")

async def test_finished_project_can_still_be_asked(client, db, world):
    await close(db, "PAY", "finished")
    await login(client, world.other)
    r = await client.post("/api/questions", json={"project_key": "PAY", "body": "Who owns billing?"})
    assert r.status_code == 201
```

In the search tests:

```python
def test_archived_projects_tasks_are_filtered_out():
    assert archived_filter([]) is None
    assert archived_filter(["p1"]) == 'NOT (kind = "task" AND project_id IN ["p1"])'
```

Also add one test through the search route, in the style of the existing search tests: an archived project's task is not found, and its project's Knowledge Base document still is.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `uv run pytest tests/projects/test_closed_elsewhere.py tests/search -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** per the Interfaces.
  - Check the request body and success status of `POST /api/questions` and the answer route against `app/a2a/router.py`, and adjust the test bodies to match. The assertions stay.

- [ ] **Step 4: Run the tests.**
  - Run `uv run pytest tests/projects tests/dashboard tests/search tests/a2a -q`. Expected: all pass.
  - Then run the whole backend suite once, in the background, with output to a file (never two pytest runs at once). Expected: green.

- [ ] **Step 5: Commit** `feat: closed projects leave the dashboard, search and question targets`.

### Task 5: Frontend: status, banner, Show archived, and the closed message

**Files:**
- Modify:
  - `frontend/src/lib/api-types.ts` (`npm run gen:api`)
  - `frontend/src/lib/errors.ts` (`project_closed`)
  - `frontend/src/app/(app)/projects/[key]/layout.tsx` (banner)
  - `frontend/src/app/(app)/projects/[key]/settings/page.tsx` (Status section)
  - `frontend/src/app/(app)/projects/page.tsx` (badge, Show archived)
- Create:
  - `frontend/src/components/project/StatusBanner.tsx`
  - `frontend/src/components/project/StatusSection.tsx`
  - `frontend/src/lib/projectStatus.ts`
- Test:
  - `frontend/src/components/project/__tests__/StatusBanner.test.tsx`
  - `frontend/src/components/project/__tests__/StatusSection.test.tsx`
  - `frontend/src/app/(app)/projects/__tests__/list.test.tsx`

**Interfaces:**
- Consumes: `ProjectOut.status`, `PUT /api/projects/{ref}/status`, `GET /api/projects/{ref}/workflows-in-progress` (Tasks 1 and 2).
- Produces, in `projectStatus.ts`:
  - `STATUS_LABEL: Record<ProjectStatus, string>`: Active, Finished, Archived.
  - `useSetProjectStatus(key)`: a mutation that invalidates `qk.project(key)` and `qk.projects()`.
  - `SHOW_ARCHIVED_KEY = "megoo.projects.showArchived"`.
- Components:
  - `StatusBanner({ project, canChange })` renders nothing for Active.
  - `StatusSection({ project, canChange })`: three buttons, Active / Finished / Archived, with `aria-pressed` on the current one.
    - Moving away from Active first fetches the in-progress count, and when it is above 0 asks: "Finish PAY?" (or "Archive PAY?") / "N workflows in progress will be paused." / ok "Finish" (or "Archive"), with the `warn` tone.
    - With no workflows in progress it changes at once.
- `canChange` = `canManage(me)` (the server enforces team management).

- [ ] **Step 1: Write the failing tests**

```tsx
it("shows the finished banner with Reopen for managers only", ...);        // text from Global Constraints; no button when canChange=false
it("Reopen sets the project active", ...);                               // PUT /api/projects/PAY/status {status:"active"}
it("asks before closing when workflows are in progress", ...);           // count 2 → dialog "2 workflows in progress will be paused."; confirm → PUT finished
it("closes at once when nothing is in progress", ...);                    // count 0 → PUT without a dialog
it("hides archived projects until Show archived is on, and remembers it", ...);  // list page; badge "Finished" on a finished one
it("explains project_closed", () => expect(errorMessage(new ApiError(409, "project_closed"))).toBe("This project is closed. Reopen it to make changes."));
```

Write each in full, with the fetch-stub pattern of `src/components/notifications/__tests__`.

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `cd frontend && npx vitest run src/components/project src/app src/lib`
  - Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Run `npm run gen:api` first.
  - The banner sits under the project tabs on every project page.
  - The Status section goes first on the Settings page, and is shown read-only (just the label) to people who can't change it.

- [ ] **Step 4: Run the checks.**
  - Run: `npx vitest run && npx tsc --noEmit && npm run lint`
  - Expected: all pass, clean.

- [ ] **Step 5: Commit** `feat(frontend): project status, the closed banner and Show archived`.

### Task 6: Frontend: delete a sprint, delete a project

**Files:**
- Modify:
  - `frontend/src/app/(app)/projects/[key]/backlog/page.tsx` (Delete beside Start and Complete)
  - `frontend/src/app/(app)/projects/[key]/reports/page.tsx` (Delete beside the sprint picker, for completed sprints)
  - `frontend/src/app/(app)/projects/[key]/settings/page.tsx` (Delete project section)
- Create: `frontend/src/components/project/DeleteProjectSection.tsx`
- Test:
  - `frontend/src/components/project/__tests__/DeleteProjectSection.test.tsx`
  - extend the backlog page tests (or add `frontend/src/app/(app)/projects/[key]/backlog/__tests__/delete.test.tsx`)

**Interfaces:**
- Consumes: `DELETE /api/sprints/{id}`, `DELETE /api/projects/{ref}`, `useMe`/`canManage`, `ConfirmDialog`'s `ask()`, `Dialog`, `Input`.
- **Sprint delete:** an icon button "Delete sprint S1", shown with `canPlan`. `ask()` uses the `danger` tone, title "Delete S1?", and this text:
  - "N tasks go back to the backlog." (planned sprints)
  - "N tasks go back to the backlog. Its burndown and velocity history is lost." (active and completed sprints)
  - Then `DELETE`, and invalidate `["sprints"]`, `["tasks"]`, `["burndown"]` and `["velocity"]`.
- **`DeleteProjectSection({ project })`** renders only for `me.role === "admin"`:
  - a "Delete project" button opens a dialog listing what goes: "its tasks, sprints, board, labels, repositories, its Knowledge Base space, what Memory learned only from it, questions sent to it, and attachments";
  - an Input labelled "Type PAY to confirm";
  - a pink "Delete project" button, disabled until the input equals the key exactly;
  - on success, `router.push("/projects")` and invalidate `qk.projects()`.

- [ ] **Step 1: Write the failing tests**

```tsx
it("is shown to admins only", ...);
it("enables Delete only when the key is typed exactly", ...);   // "pay" → disabled; "PAY" → enabled
it("deletes and goes to the projects list", ...);               // DELETE /api/projects/PAY, push("/projects")
it("deletes a sprint after saying where its tasks go", ...);    // backlog: "3 tasks go back to the backlog." then DELETE /api/sprints/s1
```

- [ ] **Step 2: Run them to verify they fail.**
  - Run: `npx vitest run src/components/project "src/app/(app)/projects"`
  - Expected: FAIL.

- [ ] **Step 3: Implement** per the Interfaces.

- [ ] **Step 4: Run the checks.**
  - Run: `npx vitest run && npx tsc --noEmit && npm run lint`
  - Expected: all pass, clean.

- [ ] **Step 5: Commit** `feat(frontend): delete sprints and projects`.

### Task 7: End-to-end

**Files:**
- Create: `frontend/e2e/lifecycle.spec.ts`

- [ ] **Step 1: Write the spec** "project lifecycle: finish, reopen, archive, delete a sprint and a project". As the admin, through the API, create team "Life Team" (admin a member), project `LIF`, two tasks, and sprint "S1" holding one of them. Then:
  1. Backlog: delete S1 with the confirmation. Both tasks now show under Backlog.
  2. Settings → Status → Finished. The banner "This project is finished. It is read-only." shows. Creating a task through the UI shows "This project is closed. Reopen it to make changes."
  3. Click Reopen. The banner disappears, and creating a task works.
  4. Status → Archived. `/projects` no longer lists LIF; with "Show archived" on it does.
  5. Settings → Delete project, type `LIF`, delete. The page lands on `/projects`, and `GET /api/projects/LIF` returns 404.

- [ ] **Step 2: Run it on a fresh stack.**
  ```
  MSYS_NO_PATHCONV=1 docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env down -v
  MSYS_NO_PATHCONV=1 docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env up -d --build --wait
  cd frontend && npx playwright test lifecycle.spec.ts
  ```
  Expected: pass.

- [ ] **Step 3: Run the whole e2e suite** on a fresh stack.
  - Expected: 21/21.

- [ ] **Step 4: Commit** `test(e2e): project lifecycle`.
