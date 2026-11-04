import uuid

from sqlalchemy import select

from app.auth.models import Role
from app.kb.models import KbDocument
from app.kb_drafts import blocks
from app.kb_drafts.models import KbDraft, KbDraftMessage
from tests.factories import login
from tests.kb_drafts.conftest import idle, start


async def _names(client, space_id) -> list[str]:
    r = await client.get("/api/kb/drafts/agents", params={"space_id": str(space_id)})
    assert r.status_code == 200, r.text
    return [a["name"] for a in r.json()]


async def _doc(db, w, title="Runbook", body="# Runbook\n\nOld text") -> KbDocument:
    doc = KbDocument(id=uuid.uuid4(), space_id=w.space.id, title=title, body_md=body, latest_revision=3)
    db.add(doc)
    await db.commit()
    return doc


async def _with_turn(db, draft_id: str, before: str, after: str) -> None:
    draft = await db.get(KbDraft, uuid.UUID(draft_id))
    draft.turn = blocks.new_turn("tidy up", before, after)
    draft.body_md = blocks.compose(draft.turn)
    await db.commit()


async def test_project_space_offers_usable_project_agents(client, db, world):
    assert await _names(client, world.space.id) == ["laptop-claude"]
    await login(client, world.manager)
    assert sorted(await _names(client, world.space.id)) == ["laptop-claude", "mgr-bot"]


async def test_team_space_offers_only_own_agents(client, db, world):
    assert sorted(await _names(client, world.team_space.id)) == ["home-bot", "laptop-claude"]
    r = await client.get("/api/kb/drafts/agents", params={"space_id": str(world.team_space.id)})
    assert {a["online"] for a in r.json()} == {False}
    assert {a["runner_ok"] for a in r.json()} == {False}


async def test_start_copies_sources_with_the_persons_access(client, db, world):
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "Deploy pipeline", "description_md": "Steps"})).json()
    doc = await _doc(db, world, "Architecture", "Services and queues")
    draft = await start(client, world, sources=[{"kind": "task", "key": task["key"]}, {"kind": "doc", "id": str(doc.id)}])
    row = await db.get(KbDraft, uuid.UUID(draft["id"]))
    assert [(s["kind"], s["title"]) for s in row.sources] == [("task", "Deploy pipeline"), ("doc", "Architecture")]
    assert "Steps" in row.sources[0]["text"] and row.sources[1]["text"] == "Services and queues"
    assert draft["messages"][0]["author"] == "person" and draft["messages"][0]["text"] == "A deploy runbook"
    assert draft["title"] == "" and draft["document"] is None

    r = await client.post("/api/kb/drafts", json={
        "space_id": str(world.space.id), "agent_id": str(world.laptop.id), "brief": "x",
        "sources": [{"kind": "task", "key": "NOPE-1"}],
    })
    assert r.status_code == 404 and r.json()["detail"] == "source_not_found"


async def test_start_on_a_document_with_a_draft_returns_it(client, db, world):
    doc = await _doc(db, world)
    first = await start(client, world, document_id=str(doc.id), brief="shorten it")
    assert first["title"] == "Runbook" and first["body_md"] == "# Runbook\n\nOld text" and first["base_revision"] == 3
    r = await client.post("/api/kb/drafts", json={
        "space_id": str(world.space.id), "agent_id": str(world.laptop.id), "brief": "another", "sources": [],
        "document_id": str(doc.id),
    })
    assert r.status_code == 200 and r.json()["id"] == first["id"]
    assert len(r.json()["messages"]) == 1
    listed = (await client.get("/api/kb/drafts")).json()
    assert [d["id"] for d in listed] == [first["id"]] and listed[0]["document_id"] == str(doc.id)


async def test_drafts_are_private(client, db, world):
    draft = await start(client, world)
    await login(client, world.other)
    assert (await client.get(f"/api/kb/drafts/{draft['id']}")).status_code == 404
    assert (await client.delete(f"/api/kb/drafts/{draft['id']}")).status_code == 404
    assert (await client.get("/api/kb/drafts")).json() == []


async def test_keep_and_undo_compose_the_body(client, db, world):
    draft = await start(client, world)
    await idle(db, draft["id"])
    await _with_turn(db, draft["id"], "# A\n\nold\n\nFAQ", "# A\n\nnew")
    got = (await client.get(f"/api/kb/drafts/{draft['id']}")).json()
    assert got["open_marks"] == 1 and [s["kind"] for s in got["segments"]] == ["text", "mark"]

    r = await client.post(f"/api/kb/drafts/{draft['id']}/marks/0/undo")
    assert r.status_code == 200, r.text
    assert r.json()["body_md"] == "# A\n\nold\n\nFAQ" and r.json()["open_marks"] == 0
    assert (await client.post(f"/api/kb/drafts/{draft['id']}/marks/0/keep")).status_code == 404

    await _with_turn(db, draft["id"], "a\n\nb\n\nc", "a\n\nB\n\nc\n\nd")
    r = await client.post(f"/api/kb/drafts/{draft['id']}/keep-all")
    assert r.json()["body_md"] == "a\n\nB\n\nc\n\nd" and r.json()["open_marks"] == 0
    await _with_turn(db, draft["id"], "a\n\nb\n\nc", "a\n\nB\n\nc\n\nd")
    r = await client.post(f"/api/kb/drafts/{draft['id']}/undo-all")
    assert r.json()["body_md"] == "a\n\nb\n\nc"


async def test_edit_settles_open_marks(client, db, world):
    draft = await start(client, world)
    await idle(db, draft["id"])
    await _with_turn(db, draft["id"], "a", "a\n\nb")
    r = await client.put(f"/api/kb/drafts/{draft['id']}", json={"body_md": "a\n\nb\n\nmine", "title": "Mine"})
    assert r.status_code == 200, r.text
    assert r.json()["open_marks"] == 0 and r.json()["body_md"] == "a\n\nb\n\nmine" and r.json()["title"] == "Mine"
    await _with_turn(db, draft["id"], "x", "y")
    r = await client.post(f"/api/kb/drafts/{draft['id']}/settle")
    assert r.json()["open_marks"] == 0 and r.json()["body_md"] == "y"


async def test_lost_write_access_is_403(client, db, world):
    draft = await start(client, world)
    world.me.role = Role.viewer
    await db.commit()
    assert (await client.get(f"/api/kb/drafts/{draft['id']}")).status_code == 403
    assert (await client.put(f"/api/kb/drafts/{draft['id']}", json={"body_md": "x"})).status_code == 403


async def test_removed_agent_is_refused(client, db, world):
    draft = await start(client, world)
    await idle(db, draft["id"])
    r = await client.patch(f"/api/kb/drafts/{draft['id']}/agent", json={"agent_id": str(world.mgr_bot.id)})
    assert r.status_code == 422 and r.json()["detail"] == "agent_not_available"
    r = await client.patch(f"/api/kb/drafts/{draft['id']}/agent", json={"agent_id": str(world.home.id)})
    assert r.status_code == 422  # not bound to the project
    r = await client.post("/api/kb/drafts", json={
        "space_id": str(world.space.id), "agent_id": str(world.mgr_bot.id), "brief": "x", "sources": [],
    })
    assert r.status_code == 422


async def test_discard_deletes_draft_and_messages(client, db, world):
    draft = await start(client, world)
    r = await client.delete(f"/api/kb/drafts/{draft['id']}")
    assert r.status_code == 204
    db.expire_all()
    assert (await db.execute(select(KbDraft))).scalars().all() == []
    assert (await db.execute(select(KbDraftMessage))).scalars().all() == []
