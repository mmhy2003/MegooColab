import json
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.service import dispatch_pending, finish_run
from app.core.db import SessionLocal
from app.kb_drafts import turns
from app.kb_drafts.models import KbDraft, KbDraftMessage
from app.notifications.models import Notification
from app.runner.protocol import RunFinished
from app.runner.registry import DRAFTS_CAPABILITY, registry
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.kb_drafts.conftest import idle, start


async def _runs(db, draft_id: str) -> list[AgentRun]:
    db.expire_all()
    return list(
        (await db.execute(
            select(AgentRun).where(AgentRun.draft_id == uuid.UUID(draft_id)).order_by(AgentRun.created_at)
        )).scalars()
    )


async def test_request_queues_a_read_only_draft_run(client, db, world):
    draft = await start(client, world)
    [first] = await _runs(db, draft["id"])
    assert first.status == RunStatus.queued and first.policy == "read_only" and first.workflow_role is None
    assert first.draft_request["request"] == "A deploy runbook" and first.resume_session_ref is None
    assert draft["state"] == "waiting"  # the agent is offline

    await idle(db, draft["id"])
    await db.execute(update(KbDraft).where(KbDraft.id == uuid.UUID(draft["id"])).values(session_ref="s1"))
    await db.commit()
    target = {"section": "Prerequisites", "text": "Before starting"}
    r = await client.post(f"/api/kb/drafts/{draft['id']}/requests", json={"text": "shorten this", "target": target})
    assert r.status_code == 200, r.text
    assert r.json()["messages"][-1]["text"] == "shorten this" and r.json()["messages"][-1]["target"] == target
    second = (await _runs(db, draft["id"]))[-1]
    assert second.resume_session_ref == "s1" and second.draft_request["target"] == target
    assert "shorten this" in second.resume_prompt and "Prerequisites" in second.resume_prompt
    assert "kb_draft_read" in second.prompt
    from app.workflow.context import DOCS_NOTE

    assert DOCS_NOTE in second.prompt


async def test_second_request_while_writing_is_409(client, db, world):
    draft = await start(client, world)
    r = await client.post(f"/api/kb/drafts/{draft['id']}/requests", json={"text": "more"})
    assert r.status_code == 409 and r.json()["detail"] == "agent_writing"


async def test_runner_without_drafts_capability_leaves_the_run_queued(client, db, world):
    draft = await start(client, world)
    sock = _FakeSocket()
    conn = await _fake_conn(world.me, {"id": str(world.laptop.id)}, sock)
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, world.me.id)
        assert [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"] == []

        conn.capabilities.add(DRAFTS_CAPABILITY)
        async with SessionLocal() as s:
            await dispatch_pending(s, world.me.id)
        [msg] = [m for m in map(json.loads, sock.sent) if m["type"] == "run_start"]
    finally:
        registry._conns.pop(world.me.id, None)
    assert msg["draft"] == {"id": draft["id"]} and msg["role"] == "kb_draft" and msg["policy"] == "read_only"
    assert msg["task"]["key"] == f"KBD-{uuid.UUID(draft['id']).hex[:12]}" and msg["task"]["project_key"] == "PAY"
    assert msg["local_path"] == "/work/pay" and msg["mcp"]["token"].startswith("mgr_")
    assert (await _runs(db, draft["id"]))[0].status == RunStatus.running


async def test_start_fields_for_team_draft_have_no_local_path(client, db, world):
    draft = await start(client, world, space_id=str(world.team_space.id), agent_id=str(world.home.id))
    [run] = await _runs(db, draft["id"])
    task, local_path, fields = await turns.start_fields(db, run)
    assert local_path == "" and task.project_key == "" and fields["draft"].id == uuid.UUID(draft["id"])


async def test_start_fields_for_project_draft_use_binding(client, db, world):
    draft = await start(client, world)
    [run] = await _runs(db, draft["id"])
    task, local_path, fields = await turns.start_fields(db, run)
    assert local_path == "/work/pay" and task.project_key == "PAY" and fields["role"] == "kb_draft"


async def test_cancelled_run_adds_a_system_message_and_keeps_the_body(client, db, world):
    draft = await start(client, world)
    r = await client.post(f"/api/kb/drafts/{draft['id']}/stop")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "idle" and r.json()["body_md"] == ""
    assert r.json()["messages"][-1] == {**r.json()["messages"][-1], "author": "system",
                                         "text": "laptop-claude stopped before changing the draft."}


async def _running(db, draft_id: str, submitted: bool) -> uuid.UUID:
    [run] = await _runs(db, draft_id)
    run_id = run.id
    run.status = RunStatus.running
    run.draft_request = {**run.draft_request, "submitted": submitted}
    await db.commit()
    return run_id


async def _notifications(db, user_id) -> list[Notification]:
    db.expire_all()
    return list((await db.execute(select(Notification).where(Notification.user_id == user_id))).scalars())


async def test_finished_run_with_submission_notifies_the_person(client, db, world):
    draft = await start(client, world)
    me_id = world.me.id
    run_id = await _running(db, draft["id"], submitted=True)
    async with SessionLocal() as s:
        s.add(KbDraftMessage(draft_id=uuid.UUID(draft["id"]), author="agent", text="Drafted 6 sections.\nMore", run_id=run_id))
        await s.execute(update(KbDraft).where(KbDraft.id == uuid.UUID(draft["id"])).values(title="Runbook"))
        await s.commit()
    async with SessionLocal() as s:
        await finish_run(s, me_id, run_id, "completed", "", None,
                         RunFinished(type="run_finished", run_id=run_id, outcome="completed", summary="", session_id="sess-9"))
    [n] = await _notifications(db, me_id)
    assert n.title == "laptop-claude updated your draft 'Runbook'" and n.body == "Drafted 6 sections."
    assert n.link == f"/kb/drafts/{draft['id']}" and n.kind == "needs_you"
    assert (await db.get(KbDraft, uuid.UUID(draft["id"]))).session_ref == "sess-9"


async def test_finished_run_without_submission_notifies_no_one(client, db, world):
    draft = await start(client, world)
    me_id = world.me.id
    run_id = await _running(db, draft["id"], submitted=False)
    async with SessionLocal() as s:
        await finish_run(s, me_id, run_id, "completed", "", None, None)
    assert await _notifications(db, me_id) == []
    got = (await client.get(f"/api/kb/drafts/{draft['id']}")).json()
    assert got["messages"][-1]["author"] == "system"


async def test_methodology_lists_kb_draft_in_the_kb_group(client, db, world):
    r = await client.get("/api/methodology")
    assert {"key": "kb_draft", "stage": "kb"}.items() <= next(m for m in r.json() if m["key"] == "kb_draft").items()
