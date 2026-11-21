"""The triggers API: members read, managers and admins write; the config is checked; the last editor is "runs as"."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.audit.models import AuditLog
from app.auth.models import Role
from app.chats.models import Chat
from app.core.db import SessionLocal
from app.crons.models import Cron
from app.projects.models import Project
from app.tasks.models import Task
from app.triggers import fire
from app.triggers.models import Trigger, TriggerFiring
from tests.factories import login, make_user
from tests.workflow.test_freestyle_engine import _end

BASE = "/api/projects/PAY/triggers"
ALL_TYPES = ["story", "task", "bug"]
SUBJECT = {"kind": "task", "label": "PAY-3", "title": "Fix the login", "link": "/projects/PAY/tasks/3", "note": "finished"}


def _body(**over) -> dict:
    body = {"name": "Release notes", "event": "task_finished", "config": {"task_types": ALL_TYPES},
            "prompt": "Write the release notes."}
    body.update(over)
    return body


async def _create(client, w, **over) -> dict:
    await login(client, w.manager)
    r = await client.post(BASE, json=_body(**over))
    assert r.status_code == 201, r.text
    return r.json()


async def _columns(client) -> dict[str, str]:
    return {c["name"]: c["id"] for c in (await client.get("/api/projects/PAY/columns")).json()}


async def _code(r) -> str:
    assert r.status_code == 422, r.text
    return r.json()["detail"]


async def _pending(trigger_id: str, **kw) -> uuid.UUID:
    async with SessionLocal() as s:
        firing = TriggerFiring(trigger_id=uuid.UUID(trigger_id), event="task_finished", subject=SUBJECT,
                               what="PAY-3 finished.", **kw)
        s.add(firing)
        await s.commit()
        return firing.id


async def _last(client, trigger_id: str) -> dict | None:
    r = await client.get(f"{BASE}/{trigger_id}")
    assert r.status_code == 200, r.text
    return r.json()["last_firing"]


async def test_members_read_managers_and_admins_write(client, db, world):
    created = await _create(client, world)
    tid = created["id"]
    assert created["project_key"] == "PAY" and created["event"] == "task_finished"
    assert created["owner"]["id"] == str(world.manager.id) and created["created_by"]["id"] == str(world.manager.id)
    assert created["any_agent"] is True and created["agent"] is None
    assert (created["keep_open"], created["notify_reply"], created["notify_problems"], created["paused"]) == (
        False, True, True, False)
    assert created["broken"] is None and created["last_firing"] is None

    await login(client, world.me)
    assert [t["name"] for t in (await client.get(BASE)).json()] == ["Release notes"]
    assert (await client.get(f"{BASE}/{tid}")).json()["prompt"] == "Write the release notes."
    assert (await client.post(BASE, json=_body())).status_code == 403
    assert (await client.patch(f"{BASE}/{tid}", json={"name": "x"})).status_code == 403
    assert (await client.post(f"{BASE}/{tid}/pause")).status_code == 403
    assert (await client.post(f"{BASE}/{tid}/resume")).status_code == 403
    assert (await client.delete(f"{BASE}/{tid}")).status_code == 403
    assert (await client.get(f"{BASE}/{uuid.uuid4()}")).status_code == 404

    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    r = await client.post(BASE, json=_body(name="By the admin", agent_id=str(world.mgr_bot.id)))
    assert r.status_code == 201, r.text
    assert r.json()["agent"] == {"id": str(world.mgr_bot.id), "name": "mgr-bot"} and r.json()["any_agent"] is False
    assert (await client.delete(f"{BASE}/{tid}")).status_code == 204
    assert (await client.get(f"{BASE}/{tid}")).status_code == 404


async def test_validation_codes(client, db, world):
    await login(client, world.manager)
    cols = await _columns(client)
    assert await _code(await client.post(BASE, json=_body(event="task_deleted"))) == "invalid_event"
    assert await _code(await client.post(BASE, json=_body(config={"task_types": ["epic"]}))) == "invalid_config"
    assert await _code(await client.post(BASE, json=_body(config={}))) == "no_task_types"
    assert await _code(await client.post(BASE, json=_body(
        config={"task_types": ["bug"], "label_id": str(uuid.uuid4())}))) == "invalid_label"
    assert await _code(await client.post(BASE, json=_body(
        event="task_moved", config={"task_types": ["bug"], "column_id": str(uuid.uuid4())}))) == "invalid_column"
    assert await _code(await client.post(BASE, json=_body(
        event="cron_found", config={"cron_id": str(uuid.uuid4())}))) == "invalid_cron"
    # the home bot is bound to no project
    assert await _code(await client.post(BASE, json=_body(agent_id=str(world.home.id)))) == "agent_not_available"
    # the sprint events need sprints
    await db.execute(update(Project).where(Project.key == "PAY").values(sprints_enabled=False))
    await db.commit()
    assert await _code(await client.post(BASE, json=_body(event="sprint_started", config={}))) == "invalid_event"

    # a good config comes back cleaned
    r = await client.post(BASE, json=_body(event="task_moved", config={"task_types": ["bug", "story", "bug"],
                                                                       "column_id": cols["Done"]}))
    assert r.status_code == 201, r.text
    assert r.json()["config"] == {"task_types": ["story", "bug"], "column_id": cols["Done"]}
    tid = r.json()["id"]
    # an edit checks the merged event and config: task_moved without its column, or a config the new event refuses
    assert await _code(await client.patch(f"{BASE}/{tid}", json={"config": {"task_types": ["bug"]}})) == "invalid_column"
    assert await _code(await client.patch(f"{BASE}/{tid}", json={"event": "pr_merged"})) == "invalid_config"
    r = await client.patch(f"{BASE}/{tid}", json={"event": "pr_merged", "config": {}})
    assert r.status_code == 200 and r.json()["event"] == "pr_merged" and r.json()["config"] == {}
    assert await _code(await client.patch(f"{BASE}/{tid}", json={"agent_id": str(world.home.id)})) == "agent_not_available"


async def test_runs_as_moves_to_the_last_editor_not_on_pause(client, db, world):
    created = await _create(client, world, agent_id=str(world.mgr_bot.id))
    tid = created["id"]
    admin = await make_user(db, role=Role.admin, name="Ada Admin")
    await login(client, admin)
    r = await client.patch(f"{BASE}/{tid}", json={"prompt": "Write better notes."})
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["owner"] == {"id": str(admin.id), "name": "Ada Admin"}
    assert edited["created_by"]["id"] == str(world.manager.id)
    assert edited["agent"]["id"] == str(world.mgr_bot.id) and edited["updated_at"] > created["updated_at"]

    await login(client, world.manager)
    assert (await client.post(f"{BASE}/{tid}/pause")).json()["paused"] is True
    resumed = (await client.post(f"{BASE}/{tid}/resume")).json()
    assert resumed["paused"] is False and resumed["owner"]["id"] == str(admin.id)

    # agent_id given as null: any free agent
    r = await client.patch(f"{BASE}/{tid}", json={"agent_id": None})
    assert r.json()["any_agent"] is True and r.json()["agent"] is None
    assert r.json()["owner"]["id"] == str(world.manager.id)


async def test_broken_reference(client, db, world):
    await login(client, world.manager)
    r = await client.post("/api/projects/PAY/columns", json={"name": "Blocked", "category": "working"})
    column = r.json()["id"]
    label = (await client.post("/api/projects/PAY/labels", json={"name": "api", "color": "#112233"})).json()["id"]
    cron = Cron(project_id=uuid.UUID(world.project["id"]), name="Nightly", prompt="p", schedule="0 2 * * *",
                timezone="UTC", created_by=world.manager.id)
    db.add(cron)
    await db.commit()
    moved = await _create(client, world, event="task_moved", config={"task_types": ALL_TYPES, "column_id": column})
    labelled = await _create(client, world, config={"task_types": ALL_TYPES, "label_id": label})
    found = await _create(client, world, event="cron_found", config={"cron_id": str(cron.id)})
    any_cron = await _create(client, world, event="cron_found", config={"cron_id": None})
    assert [moved["broken"], labelled["broken"], found["broken"], any_cron["broken"]] == [None] * 4

    assert (await client.delete(f"/api/projects/PAY/columns/{column}")).status_code == 204
    assert (await client.delete(f"/api/projects/PAY/labels/{label}")).status_code == 204
    await db.delete(cron)
    await db.commit()

    broken = {t["id"]: t["broken"] for t in (await client.get(BASE)).json()}
    assert broken == {moved["id"]: "column_deleted", labelled["id"]: "label_deleted",
                      found["id"]: "cron_deleted", any_cron["id"]: None}
    # a move into any other column matches nothing
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "Ship it"})).json()
    r = await client.post(f"/api/tasks/{task['key']}/move", json={"column_id": (await _columns(client))["Done"]})
    assert r.status_code == 200, r.text
    count = await db.scalar(select(TriggerFiring.id).where(TriggerFiring.trigger_id == uuid.UUID(moved["id"])))
    assert count is None


async def test_last_firing_and_results(client, db, world):
    trigger = await _create(client, world, agent_id=str(world.mgr_bot.id))
    tid = trigger["id"]
    await db.execute(update(Trigger).where(Trigger.id == uuid.UUID(tid)).values(paused=True))
    await db.commit()
    await _pending(tid)
    await fire.tick()  # paused meanwhile: skipped
    last = await _last(client, tid)
    assert (last["result"], last["excerpt"], last["chat_id"]) == ("skipped", "paused", None)
    assert last["subject"] == SUBJECT

    await db.execute(update(Trigger).where(Trigger.id == uuid.UUID(tid)).values(paused=False))
    await db.commit()
    firing_id = await _pending(tid)
    last = await _last(client, tid)
    assert (last["id"], last["result"], last["excerpt"], last["agent"]) == (str(firing_id), "starting", None, None)

    await fire.tick()
    last = await _last(client, tid)
    assert last["result"] == "waiting_agent" and last["agent"]["id"] == str(world.mgr_bot.id)
    async with SessionLocal() as s:
        chat_id = (await s.get(TriggerFiring, firing_id)).chat_id
        task_id = await s.scalar(select(Task.id).where(Task.chat_id == chat_id))
        run_id = await s.scalar(select(AgentRun.id).where(AgentRun.task_id == task_id))
        await s.execute(update(AgentRun).where(AgentRun.id == run_id).values(status=RunStatus.running))
        await s.commit()
    last = await _last(client, tid)
    assert (last["result"], last["chat_id"]) == ("working", str(chat_id))

    await _end(run_id, "completed", "Wrote the notes for PAY-3.")
    last = await _last(client, tid)
    assert (last["result"], last["excerpt"]) == ("replied", "Wrote the notes for PAY-3.")


async def test_failed_and_question_results(client, db, world):
    from app.workflow.models import WorkflowQuestion

    tid = (await _create(client, world, agent_id=str(world.mgr_bot.id), keep_open=True))["id"]
    failing = await _pending(tid)
    await fire.tick()
    async with SessionLocal() as s:
        chat_id = (await s.get(TriggerFiring, failing)).chat_id
        task_id = await s.scalar(select(Task.id).where(Task.chat_id == chat_id))
        run_id = await s.scalar(select(AgentRun.id).where(AgentRun.task_id == task_id))
    await _end(run_id, "failed", reason="agent_error")
    last = await _last(client, tid)
    assert (last["result"], last["excerpt"]) == ("failed", "agent_error")

    asking = await _pending(tid)
    await fire.tick()
    async with SessionLocal() as s:
        chat_id = (await s.get(TriggerFiring, asking)).chat_id
        task_id = await s.scalar(select(Task.id).where(Task.chat_id == chat_id))
        run_id = await s.scalar(select(AgentRun.id).where(AgentRun.task_id == task_id))
        s.add(WorkflowQuestion(task_id=task_id, run_id=run_id, stage="build", body="Which tag?", choices=[]))
        await s.commit()
    await _end(run_id, "completed")
    last = await _last(client, tid)
    assert (last["result"], last["excerpt"]) == ("question", "Which tag?")


async def test_delete_cascades_firings_and_keeps_chats(client, db, world):
    tid = (await _create(client, world, agent_id=str(world.mgr_bot.id)))["id"]
    firing_id = await _pending(tid)
    await fire.tick()
    async with SessionLocal() as s:
        chat_id = (await s.get(TriggerFiring, firing_id)).chat_id
    assert chat_id is not None

    assert (await client.delete(f"{BASE}/{tid}")).status_code == 204
    async with SessionLocal() as s:
        assert await s.get(Trigger, uuid.UUID(tid)) is None
        assert await s.get(TriggerFiring, firing_id) is None
        assert await s.get(Chat, chat_id) is not None
    r = await client.get(f"/api/chats/{chat_id}")
    assert r.status_code == 200 and r.json()["trigger"] is None


async def test_pause_resume_delete_on_a_finished_project(client, db, world):
    tid = (await _create(client, world))["id"]
    assert (await client.put("/api/projects/PAY/status", json={"status": "finished"})).status_code == 200
    assert (await client.post(BASE, json=_body())).status_code == 409
    assert (await client.patch(f"{BASE}/{tid}", json={"name": "x"})).status_code == 409
    assert (await client.post(f"{BASE}/{tid}/pause")).json()["paused"] is True
    assert (await client.post(f"{BASE}/{tid}/resume")).json()["paused"] is False
    assert (await client.get(BASE)).status_code == 200
    assert (await client.delete(f"{BASE}/{tid}")).status_code == 204


async def test_audit_records(client, db, world):
    tid = (await _create(client, world))["id"]
    await client.patch(f"{BASE}/{tid}", json={"name": "Renamed"})
    await client.post(f"{BASE}/{tid}/pause")
    await client.post(f"{BASE}/{tid}/resume")
    await client.delete(f"{BASE}/{tid}")
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.target_id == uuid.UUID(tid)).order_by(AuditLog.created_at, AuditLog.id)
    )).scalars().all()
    assert [r.action for r in rows] == ["trigger.created", "trigger.updated", "trigger.paused", "trigger.resumed",
                                        "trigger.deleted"]
    assert all(r.actor_user_id == world.manager.id and r.target_type == "trigger" for r in rows)
    assert rows[1].data == {"name": "Renamed", "project_id": world.project["id"], "event": "task_finished"}
