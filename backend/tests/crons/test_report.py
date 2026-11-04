"""The cron report: what the agent found, and what MegooColab does with it per the cron's mode."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.service import finish_run
from app.core.db import SessionLocal
from app.crons import scheduler
from app.crons.models import Cron, CronRun
from app.kb.models import KbDocument, KbRevision
from app.notifications.models import Notification
from app.projects.models import Label
from app.tasks.models import Comment, Task, task_labels
from tests.factories import login
from tests.mcp.test_workflow_tools import _run_token, _tool

BASE = "/api/projects/PAY/crons"


async def _cron_run(client, world, mode: str, **over) -> tuple[uuid.UUID, AgentRun]:
    """A cron of the manager's, due and started: its AgentRun running, on the manager's agent."""
    await login(client, world.manager)
    body = {"name": "Nightly check", "prompt": "Check it.", "schedule": "0 2 * * *", "timezone": "UTC",
            "agent_id": str(world.mgr_bot.id), "mode": mode}
    body.update(over)
    cron_id = uuid.UUID((await client.post(BASE, json=body)).json()["id"])
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        await s.execute(update(Cron).where(Cron.id == cron_id).values(next_run_at=now - timedelta(minutes=1)))
        await s.commit()
    await scheduler.tick(now)
    async with SessionLocal() as s:
        run = (await s.execute(select(AgentRun).where(AgentRun.cron_run_id.is_not(None))
                               .order_by(AgentRun.created_at.desc()).limit(1))).scalar_one()
    return cron_id, run


async def _report(tc, run, **report):
    token = await _run_token(run)
    return _tool(tc, token, "submit_cron_report", **{"summary": "Checked.", "findings": [], **report})


async def _finish(owner_id, run) -> None:
    async with SessionLocal() as s:
        await finish_run(s, owner_id, run.id, "completed", "", None, None)


async def _cron_runs(cron_id) -> list[CronRun]:
    async with SessionLocal() as s:
        return list((await s.execute(select(CronRun).where(CronRun.cron_id == cron_id))).scalars())


async def _tasks(*where) -> list[Task]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Task).where(*where))).scalars())


async def test_report_only_mode_creates_nothing(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    owner = world.manager.id
    cron_id, run = await _cron_run(client, world, "report")
    before = len(await _tasks())
    err, out = await _report(tc, run, findings=[{"title": "Old lib", "detail": "x", "new_task": True}])
    assert not err, out
    await _finish(owner, run)
    [cr] = await _cron_runs(cron_id)
    assert cr.status == "done" and cr.report["findings"][0]["title"] == "Old lib" and cr.tasks_created == 0
    assert len(await _tasks()) == before


async def test_tasks_mode_creates_at_most_five_labelled_tasks(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    owner = world.manager.id
    cron_id, run = await _cron_run(client, world, "tasks")
    findings = [{"title": f"Problem {i}", "detail": f"Why {i}", "new_task": True} for i in range(7)]
    err, out = await _report(tc, run, findings=findings)
    assert not err, out
    [cr] = await _cron_runs(cron_id)
    assert cr.tasks_created == 5 and any("2 more" in n for n in cr.report["notes"])
    created = await _tasks(Task.title.like("Problem %"))
    assert len(created) == 5
    async with SessionLocal() as s:
        label = (await s.execute(select(Label).where(Label.name == "from cron"))).scalar_one()
        labelled = set((await s.execute(select(task_labels.c.task_id).where(task_labels.c.label_id == label.id))).scalars())
        assert {t.id for t in created} <= labelled
    assert f"/projects/PAY/crons/{cron_id}?run={cr.id}" in created[0].description_md
    assert all(f.get("task_key") for f in cr.report["findings"][:5])


async def test_existing_task_gets_a_comment_and_foreign_keys_are_ignored(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id, run = await _cron_run(client, world, "tasks")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "Upgrade sqlalchemy"})).json()
    err, out = await _report(tc, run, findings=[
        {"title": "sqlalchemy behind", "detail": "Still 1.4", "existing_task_key": task["key"]},
        {"title": "Other", "detail": "x", "existing_task_key": "WEB-1"},
    ])
    assert not err, out
    async with SessionLocal() as s:
        bodies = (await s.execute(select(Comment.body_md).where(Comment.task_id == uuid.UUID(task["id"])))).scalars().all()
    assert any(f"/projects/PAY/crons/{cron_id}" in b for b in bodies)
    [cr] = await _cron_runs(cron_id)
    assert cr.report["findings"][0]["task_key"] == task["key"] and "WEB-1" in " ".join(cr.report["notes"])


async def test_kb_mode_writes_one_document_and_recreates_it(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    owner = world.manager.id
    cron_id, run = await _cron_run(client, world, "kb", kb_title="Dependency status")
    assert not (await _report(tc, run, document_md="# Status\n\nAll good."))[0]
    await _finish(owner, run)
    async with SessionLocal() as s:
        doc_id = (await s.get(Cron, cron_id)).kb_document_id
        doc = await s.get(KbDocument, doc_id)
        assert (doc.title, doc.body_md, doc.folder_id) == ("Dependency status", "# Status\n\nAll good.", None)
    run2 = (await client.post(f"{BASE}/{cron_id}/run-now")).json()
    async with SessionLocal() as s:
        agent_run = (await s.execute(select(AgentRun).where(AgentRun.cron_run_id == uuid.UUID(run2["id"])))).scalar_one()
    assert not (await _report(tc, agent_run, document_md="# Status\n\nOne problem."))[0]
    await _finish(owner, agent_run)
    async with SessionLocal() as s:
        revs = (await s.execute(select(KbRevision).where(KbRevision.document_id == doc_id)
                                .order_by(KbRevision.revision))).scalars().all()
        assert [r.summary for r in revs] == ["Cron: Nightly check", "Cron: Nightly check"]
        await s.delete(await s.get(KbDocument, doc_id))
        await s.commit()
    run3 = (await client.post(f"{BASE}/{cron_id}/run-now")).json()
    async with SessionLocal() as s:
        agent_run = (await s.execute(select(AgentRun).where(AgentRun.cron_run_id == uuid.UUID(run3["id"])))).scalar_one()
    assert not (await _report(tc, agent_run, document_md="# Status\n\nBack."))[0]
    async with SessionLocal() as s:
        new_id = (await s.get(Cron, cron_id)).kb_document_id
        assert new_id not in (None, doc_id) and (await s.get(KbDocument, new_id)).body_md == "# Status\n\nBack."


async def test_cron_run_reads_only_its_project_tasks(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    _, run = await _cron_run(client, world, "tasks")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "Known"})).json()
    token = await _run_token(run)
    err, out = _tool(tc, token, "list_tasks", project_key="PAY")
    assert not err and any(t["key"] == task["key"] for t in out), out
    assert not _tool(tc, token, "get_task", key=task["key"])[0]
    for name, args in (("list_tasks", {"project_key": "WEB"}), ("kb_write", {"title": "t", "body_md": "b"}),
                       ("ask_project", {"project_key": "PAY", "question": "q"}),
                       ("comment_on_task", {"key": task["key"], "body_md": "x"})):
        err, text = _tool(tc, token, name, **args)
        assert err and "not_allowed_in_role" in text, (name, text)


async def test_findings_notify_creator_and_managers(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    owner = world.manager.id
    cron_id, run = await _cron_run(client, world, "report")
    await _report(tc, run, findings=[{"title": "Old lib", "detail": "x"}])
    await _finish(owner, run)
    async with SessionLocal() as s:
        notes = (await s.execute(select(Notification).where(Notification.user_id == owner))).scalars().all()
    assert [n.title for n in notes] == ["Cron Nightly check: 1 finding"]
    # a run with nothing found tells no one (notify_every is off)
    run2 = (await client.post(f"{BASE}/{cron_id}/run-now")).json()
    async with SessionLocal() as s:
        agent_run = (await s.execute(select(AgentRun).where(AgentRun.cron_run_id == uuid.UUID(run2["id"])))).scalar_one()
        await s.execute(update(AgentRun).where(AgentRun.id == agent_run.id).values(status=RunStatus.running))
        await s.commit()
    await _report(tc, agent_run, nothing_new=True)
    await _finish(owner, agent_run)
    async with SessionLocal() as s:
        assert len((await s.execute(select(Notification).where(Notification.user_id == owner))).scalars().all()) == 1
