import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.core.config import get_settings
from app.crons.models import Cron, CronRun
from app.projects.models import Project, ProjectRepository
from app.sprints.models import Sprint
from app.tasks.models import Task
from app.triggers import events
from app.triggers.models import Trigger, TriggerEvent
from tests.factories import login, make_project

OTHER_EVENTS = ("sprint_started", "sprint_completed", "epic_completed", "cron_found", "pr_merged")


async def _project(db, w) -> Project:
    db.expire_all()
    return await db.get(Project, uuid.UUID(w.project["id"]))


async def _columns(client, key: str = "PAY") -> dict[str, str]:
    r = await client.get(f"/api/projects/{key}/columns")
    assert r.status_code == 200, r.text
    return {c["name"]: c["id"] for c in r.json()}


async def _task(client, title: str, **body) -> dict:
    r = await client.post("/api/projects/PAY/tasks", json={"title": title, **body})
    assert r.status_code == 201, r.text
    return r.json()


async def _set(db, task: dict, **values) -> None:
    await db.execute(update(Task).where(Task.id == uuid.UUID(task["id"])).values(**values))
    await db.commit()


async def _refused(call) -> str:
    with pytest.raises(HTTPException) as e:
        await call
    assert e.value.status_code == 422
    return e.value.detail


async def _cron(db, project_id, name: str = "Nightly audit") -> Cron:
    cron = Cron(project_id=project_id, name=name, prompt="Look", schedule="0 3 * * *", timezone="UTC")
    db.add(cron)
    await db.commit()
    return cron


async def _cron_run(db, cron: Cron, at: datetime, *, findings: list | None = None, status: str = "done") -> CronRun:
    report = None if findings is None else {"summary": "Two problems found", "findings": findings, "submitted": True}
    run = CronRun(cron_id=cron.id, scheduled_at=at, status=status, report=report, finished_at=at)
    db.add(run)
    await db.commit()
    return run


async def _sprint(db, w, name: str, state: str, **values) -> Sprint:
    sprint = Sprint(project_id=uuid.UUID(w.project["id"]), name=name, goal=values.pop("goal", ""),
                    start_date=date(2026, 11, 2), end_date=date(2026, 11, 16), state=state, **values)
    db.add(sprint)
    await db.commit()
    return sprint


async def _trigger(db, w, event: str, config: dict) -> Trigger:
    t = Trigger(project_id=uuid.UUID(w.project["id"]), name="t", event=event, config=config, prompt="Go")
    db.add(t)
    await db.commit()
    return t


async def test_sprint_events_are_refused_without_sprints(db, world):
    project = await _project(db, world)
    for event in ("sprint_started", "sprint_completed"):
        assert events.spec(event).sprints_only
        assert await events.spec(event).validate(db, project, {}) == {}
    await db.execute(update(Project).where(Project.id == project.id).values(sprints_enabled=False))
    await db.commit()
    project = await _project(db, world)
    for event in ("sprint_started", "sprint_completed"):
        assert await _refused(events.spec(event).validate(db, project, {})) == "invalid_event"
    assert await events.spec("epic_completed").validate(db, project, {}) == {}
    assert not events.spec("epic_completed").sprints_only


async def test_cron_found_accepts_any_or_one_of_the_projects_crons(client, db, world):
    project = await _project(db, world)
    mine = await _cron(db, project.id)
    other, _, _ = await make_project(client, db, "OPS")
    theirs = await _cron(db, uuid.UUID(other["id"]))

    validate = events.spec("cron_found").validate
    assert await validate(db, project, {}) == {}
    assert await validate(db, project, {"cron_id": None}) == {}
    assert await validate(db, project, {"cron_id": str(mine.id)}) == {"cron_id": str(mine.id)}
    assert await _refused(validate(db, project, {"cron_id": str(theirs.id)})) == "invalid_cron"
    assert await _refused(validate(db, project, {"cron_id": str(uuid.uuid4())})) == "invalid_cron"
    assert await _refused(validate(db, project, {"cron_id": "nope"})) == "invalid_cron"
    assert await _refused(validate(db, project, {"cron_id": 3})) == "invalid_config"
    assert await _refused(validate(db, project, {"cron_id": None, "x": 1})) == "invalid_config"

    matches = events.spec("cron_found").matches
    payload = {"cron_id": str(mine.id), "cron_run_id": str(uuid.uuid4())}
    assert matches({}, payload)
    assert matches({"cron_id": str(mine.id)}, payload)
    assert not matches({"cron_id": str(theirs.id)}, payload)


async def test_describe_sprint_lists_its_tasks(client, db, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://colab.example.com/")
    await login(client, world.manager)
    cols = await _columns(client)
    a, b = await _task(client, "Refunds fail", type="bug"), await _task(client, "Export CSV", type="story")
    chat = await _task(client, "A chat round", type="bug")
    sprint = await _sprint(db, world, "Sprint 7", "active", goal="Ship refunds")
    for t in (a, b, chat):
        await _set(db, t, sprint_id=sprint.id)
    await _set(db, b, column_id=uuid.UUID(cols["Done"]))
    await _set(db, chat, in_chat=True)
    column_a = next(n for n, i in cols.items() if i == a["column_id"])

    d = await events.spec("sprint_started").describe(db, {"sprint_id": str(sprint.id)})
    assert d.subject == {"kind": "sprint", "label": "Sprint 7", "title": "Ship refunds",
                         "link": "/projects/PAY/backlog", "note": "started"}
    lines = d.what.splitlines()
    assert lines[0] == 'Sprint "Sprint 7" was started.'
    assert "Dates: 2026-11-02 to 2026-11-16" in lines
    assert "Goal: Ship refunds" in lines
    assert "Link: https://colab.example.com/projects/PAY/backlog" in lines
    assert not any(line.startswith("Points:") for line in lines)
    assert d.what.endswith(f"Tasks:\n- {a['key']} [{column_a}] Refunds fail\n- {b['key']} [Done] Export CSV")
    assert "A chat round" not in d.what

    sprint_id = sprint.id
    await db.execute(update(Sprint).where(Sprint.id == sprint_id).values(
        state="completed", completed_at=datetime.now(UTC), committed_points=13, completed_points=8, goal=""))
    await db.commit()
    db.expire_all()
    d = await events.spec("sprint_completed").describe(db, {"sprint_id": str(sprint_id)})
    assert d.subject["note"] == "completed" and d.subject["title"] == ""
    assert d.what.splitlines()[0] == 'Sprint "Sprint 7" was completed.'
    assert "Points: 8 of 13 committed points completed" in d.what.splitlines()
    assert not any(line.startswith("Goal:") for line in d.what.splitlines())


async def test_describe_epic_lists_its_tasks(client, db, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://colab.example.com/")
    await login(client, world.manager)
    cols = await _columns(client)
    epic = await _task(client, "Payments v2", type="epic", description_md="All of payments, again.")
    a = await _task(client, "Refunds", type="story", parent_id=epic["id"])
    b = await _task(client, "Invoices", type="task", parent_id=epic["id"])
    for t in (a, b):
        await _set(db, t, column_id=uuid.UUID(cols["Done"]))
    number = epic["key"].split("-")[1]

    d = await events.spec("epic_completed").describe(db, {"epic_id": epic["id"], "task_id": b["id"]})
    assert d.subject == {"kind": "epic", "label": epic["key"], "title": "Payments v2",
                         "link": f"/projects/PAY/tasks/{number}", "note": "completed"}
    lines = d.what.splitlines()
    assert lines[0] == f'Epic {epic["key"]} "Payments v2" was completed: every task of it is in a Done column.'
    assert lines[1] == f'Event: {b["key"]} "Invoices" was the last to finish'
    assert lines[2] == f"Link: https://colab.example.com/projects/PAY/tasks/{number}"
    assert "Description:\nAll of payments, again." in d.what
    assert d.what.endswith(f"Tasks:\n- {a['key']} [Done] Refunds\n- {b['key']} [Done] Invoices")


async def test_describe_cron_lists_findings(db, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://colab.example.com/")
    cron = await _cron(db, uuid.UUID(world.project["id"]))
    at = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
    run = await _cron_run(db, cron, at, findings=[
        {"title": "Stale dependency", "detail": "requests is 3 majors behind"},
        {"title": "Flaky test", "detail": "test_speed fails under load", "task_key": "PAY-9"},
    ])

    d = await events.spec("cron_found").describe(db, {"cron_id": str(cron.id), "cron_run_id": str(run.id)})
    link = f"/projects/PAY/crons/{cron.id}?run={run.id}"
    assert d.subject == {"kind": "cron_run", "label": "Nightly audit", "title": "Two problems found",
                         "link": link, "note": "2 findings"}
    assert d.what.splitlines() == [
        'Cron "Nightly audit" finished a run on 2026-11-20 03:00 UTC with 2 findings.',
        f"Link: https://colab.example.com{link}",
        "",
        "Summary:",
        "Two problems found",
        "",
        "Findings:",
        "- Stale dependency: requests is 3 majors behind",
        "- Flaky test: test_speed fails under load (task PAY-9)",
    ]

    one = await _cron_run(db, cron, at + timedelta(days=1), findings=[{"title": "Only", "detail": "one"}])
    d = await events.spec("cron_found").describe(db, {"cron_id": str(cron.id), "cron_run_id": str(one.id)})
    assert d.subject["note"] == "1 finding"
    assert "with 1 finding." in d.what


async def test_describe_pr(db, world):
    repo = ProjectRepository(project_id=uuid.UUID(world.project["id"]), name="payments-api",
                             url="https://github.com/acme/payments-api", provider="github")
    db.add(repo)
    await db.commit()
    url = "https://github.com/acme/payments-api/pull/42"
    payload = {"repo_id": str(repo.id), "number": 42, "title": "Bump requests", "url": url,
               "branch": "deps/requests", "base": "main", "actor": "octocat"}

    d = await events.spec("pr_merged").describe(db, payload)
    assert d.subject == {"kind": "pr", "label": "#42", "title": "Bump requests", "link": url,
                         "note": "merged into main"}
    assert d.what.splitlines() == [
        'Pull request #42 "Bump requests" was merged into main of repository payments-api by octocat.',
        "Branch: deps/requests",
        f"URL: {url}",
    ]


async def test_latest_for_sprint_epic_and_cron(client, db, world):
    assert events.REGISTRY["pr_merged"].latest is None

    started = await _trigger(db, world, TriggerEvent.sprint_started, {})
    completed = await _trigger(db, world, TriggerEvent.sprint_completed, {})
    assert await events.spec("sprint_started").latest(db, started) is None
    assert await events.spec("sprint_completed").latest(db, completed) is None
    now = datetime.now(UTC)
    await _sprint(db, world, "Planned", "planned")
    old = await _sprint(db, world, "Old", "completed", completed_at=now - timedelta(days=20))
    new = await _sprint(db, world, "New", "completed", completed_at=now - timedelta(days=5))
    assert await events.spec("sprint_started").latest(db, started) == {"sprint_id": str(new.id)}
    assert await events.spec("sprint_completed").latest(db, completed) == {"sprint_id": str(new.id)}
    assert old.id != new.id
    active = await _sprint(db, world, "Now", "active")
    assert await events.spec("sprint_started").latest(db, started) == {"sprint_id": str(active.id)}
    assert await events.spec("sprint_completed").latest(db, completed) == {"sprint_id": str(new.id)}

    await login(client, world.manager)
    cols = await _columns(client)
    epic_trigger = await _trigger(db, world, TriggerEvent.epic_completed, {})
    empty = await _task(client, "No children", type="epic")
    half = await _task(client, "Half done", type="epic")
    done = await _task(client, "All done", type="epic")
    h1 = await _task(client, "h1", type="story", parent_id=half["id"])
    await _task(client, "h2", type="story", parent_id=half["id"])
    d1 = await _task(client, "d1", type="story", parent_id=done["id"])
    d2 = await _task(client, "d2", type="bug", parent_id=done["id"])
    open_round = await _task(client, "chat round", type="bug", parent_id=done["id"])
    await _set(db, open_round, in_chat=True)  # a chat round is not one of the epic's tasks
    assert await events.spec("epic_completed").latest(db, epic_trigger) is None
    for t, minutes in ((h1, 1), (d1, 2), (d2, 3)):
        await _set(db, t, column_id=uuid.UUID(cols["Done"]), completed_at=now + timedelta(minutes=minutes))
    assert empty["id"] != done["id"]
    assert await events.spec("epic_completed").latest(db, epic_trigger) == {"epic_id": done["id"],
                                                                            "task_id": d2["id"]}

    project_id = uuid.UUID(world.project["id"])
    cron_a, cron_b = await _cron(db, project_id, "A"), await _cron(db, project_id, "B")
    any_cron = await _trigger(db, world, TriggerEvent.cron_found, {})
    only_a = await _trigger(db, world, TriggerEvent.cron_found, {"cron_id": str(cron_a.id)})
    assert await events.spec("cron_found").latest(db, any_cron) is None
    found = [{"title": "t", "detail": "d"}]
    a_run = await _cron_run(db, cron_a, now - timedelta(hours=5), findings=found)
    await _cron_run(db, cron_a, now - timedelta(hours=4), findings=[])  # nothing found
    await _cron_run(db, cron_a, now - timedelta(hours=3))  # no report
    await _cron_run(db, cron_a, now - timedelta(hours=2), findings=found, status="failed")
    b_run = await _cron_run(db, cron_b, now - timedelta(hours=1), findings=found)
    assert await events.spec("cron_found").latest(db, any_cron) == {"cron_id": str(cron_b.id),
                                                                    "cron_run_id": str(b_run.id)}
    payload = await events.spec("cron_found").latest(db, only_a)
    assert payload == {"cron_id": str(cron_a.id), "cron_run_id": str(a_run.id)}
    assert events.spec("cron_found").matches(only_a.config, payload)


async def test_other_events_take_no_config(db, world):
    project = await _project(db, world)
    for event in OTHER_EVENTS:
        validate = events.spec(event).validate
        assert await _refused(validate(db, project, {"x": 1})) == "invalid_config"
        assert await _refused(validate(db, project, {"task_types": ["bug"]})) == "invalid_config"
        assert await _refused(validate(db, project, [])) == "invalid_config"
    for event in ("sprint_started", "sprint_completed", "epic_completed", "pr_merged"):
        assert await events.spec(event).validate(db, project, {}) == {}
        assert events.spec(event).matches({}, {})
