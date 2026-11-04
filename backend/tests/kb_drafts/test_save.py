import json
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.kb.models import KbDocument, KbRevision
from app.kb_drafts.models import KbDraft
from app.runner.registry import DRAFTS_CAPABILITY, registry
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.kb_drafts.conftest import idle, start


async def _doc(db, w, body="# Runbook\n\nOld text") -> uuid.UUID:
    doc = KbDocument(id=uuid.uuid4(), space_id=w.space.id, title="Runbook", body_md=body, latest_revision=3,
                     created_by=w.me.id)
    db.add(doc)
    await db.commit()
    return doc.id


async def _sent(sock, kind: str) -> list[dict]:
    return [m for m in map(json.loads, sock.sent) if m["type"] == kind]


async def _online(w):
    sock = _FakeSocket()
    conn = await _fake_conn(w.me, {"id": str(w.laptop.id)}, sock)
    conn.capabilities.add(DRAFTS_CAPABILITY)
    return sock


async def test_save_new_document_credits_person_and_agent(client, db, world):
    me_id, laptop_id, space_id = world.me.id, world.laptop.id, world.space.id
    draft = await start(client, world)
    await idle(db, draft["id"])
    await client.put(f"/api/kb/drafts/{draft['id']}", json={"title": "Deploying payments", "body_md": "# Deploy"})
    r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={})
    assert r.status_code == 200, r.text
    doc_id = uuid.UUID(r.json()["document_id"])
    db.expire_all()
    doc = await db.get(KbDocument, doc_id)
    assert (doc.title, doc.body_md, doc.space_id) == ("Deploying payments", "# Deploy", space_id)
    rev = (await db.execute(select(KbRevision).where(KbRevision.document_id == doc_id))).scalar_one()
    assert (rev.author_user_id, rev.author_agent_id, rev.summary) == (me_id, laptop_id, "Written with laptop-claude")
    assert await db.get(KbDraft, uuid.UUID(draft["id"])) is None


async def test_save_needs_a_title(client, db, world):
    draft = await start(client, world)
    await idle(db, draft["id"])
    r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={})
    assert r.status_code == 422 and r.json()["detail"] == "title_required"


async def test_save_while_the_agent_writes_is_409(client, db, world):
    draft = await start(client, world)
    r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={})
    assert r.status_code == 409 and r.json()["detail"] == "agent_writing"


async def test_save_existing_document_conflict_then_force(client, db, world):
    doc_id = await _doc(db, world)
    draft = await start(client, world, document_id=str(doc_id))
    await idle(db, draft["id"])
    await client.put(f"/api/kb/drafts/{draft['id']}", json={"body_md": "# Runbook\n\nNew text"})
    await db.execute(update(KbDocument).where(KbDocument.id == doc_id).values(latest_revision=4))
    await db.commit()
    r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={"summary": "shorter"})
    assert r.status_code == 409 and r.json()["detail"] == "kb_conflict"
    db.expire_all()
    assert await db.get(KbDraft, uuid.UUID(draft["id"])) is not None
    r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={"summary": "shorter", "force": True})
    assert r.status_code == 200, r.text
    db.expire_all()
    doc = await db.get(KbDocument, doc_id)
    assert doc.latest_revision == 5 and doc.body_md == "# Runbook\n\nNew text"


async def test_bring_in_moves_the_base_and_queues_a_turn_with_the_newer_text(client, db, world):
    doc_id = await _doc(db, world)
    draft = await start(client, world, document_id=str(doc_id))
    await idle(db, draft["id"])
    await db.execute(update(KbDocument).where(KbDocument.id == doc_id).values(latest_revision=4, body_md="# Theirs"))
    await db.commit()
    r = await client.post(f"/api/kb/drafts/{draft['id']}/bring-in")
    assert r.status_code == 200, r.text
    assert r.json()["base_revision"] == 4 and "rev 4" in r.json()["messages"][-1]["text"]
    db.expire_all()
    run = (await db.execute(
        select(AgentRun).where(AgentRun.draft_id == uuid.UUID(draft["id"]), AgentRun.status == RunStatus.queued)
    )).scalar_one()
    assert run.draft_request["newer"] == {"revision": 4, "body_md": "# Theirs"}


async def test_save_tells_the_runner_to_remove_the_draft_folder(client, db, world):
    me_id = world.me.id
    draft = await start(client, world)
    await idle(db, draft["id"])
    await client.put(f"/api/kb/drafts/{draft['id']}", json={"title": "T", "body_md": "x"})
    sock = await _online(world)
    try:
        r = await client.post(f"/api/kb/drafts/{draft['id']}/save", json={})
    finally:
        registry._conns.pop(me_id, None)
    assert r.status_code == 200
    assert await _sent(sock, "draft_done") == [
        {"type": "draft_done", "agent_id": str(world.laptop.id), "draft_id": draft["id"]}
    ]


async def test_save_with_runner_offline_still_succeeds(client, db, world):
    draft = await start(client, world)
    await idle(db, draft["id"])
    await client.put(f"/api/kb/drafts/{draft['id']}", json={"title": "T", "body_md": "x"})
    assert (await client.post(f"/api/kb/drafts/{draft['id']}/save", json={})).status_code == 200


async def test_discard_cancels_the_running_turn(client, db, world):
    me_id = world.me.id
    sock = await _online(world)
    try:
        draft = await start(client, world)  # dispatched at once: the agent is online
        assert len(await _sent(sock, "run_start")) == 1
        assert (await client.delete(f"/api/kb/drafts/{draft['id']}")).status_code == 204
    finally:
        registry._conns.pop(me_id, None)
    assert len(await _sent(sock, "run_cancel")) == 1 and len(await _sent(sock, "draft_done")) == 1


async def test_deleting_the_document_stops_draft_runs(client, db, world):
    me_id = world.me.id
    doc_id = await _doc(db, world)
    sock = await _online(world)
    try:
        draft = await start(client, world, document_id=str(doc_id))
        assert len(await _sent(sock, "run_start")) == 1
        assert (await client.delete(f"/api/kb/documents/{doc_id}")).status_code == 204
    finally:
        registry._conns.pop(me_id, None)
    assert len(await _sent(sock, "run_cancel")) == 1 and len(await _sent(sock, "draft_done")) == 1
    db.expire_all()
    assert await db.get(KbDraft, uuid.UUID(draft["id"])) is None
