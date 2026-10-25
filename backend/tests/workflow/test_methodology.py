from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.db import SessionLocal
from app.workflow import methodology
from app.workflow.models import MethodologyVersion
from tests.factories import login, make_user


async def _count(db) -> int:
    return (await db.execute(select(func.count()).select_from(MethodologyVersion))).scalar_one()


async def test_seed_creates_v1_for_all_nine_keys_once(db):
    await methodology.seed_defaults(db)
    await db.commit()
    await methodology.seed_defaults(db)
    await db.commit()
    assert await _count(db) == 9
    versions = set((await db.execute(select(MethodologyVersion.version))).scalars())
    assert versions == {1}
    assert sorted(methodology.ALL_KEYS) == sorted(
        (await db.execute(select(MethodologyVersion.key))).scalars().all()
    )


async def test_every_default_mentions_its_tools(db):
    await methodology.seed_defaults(db)
    body = {k: (await methodology.current(db, k)).body_md for k in methodology.ALL_KEYS}
    assert "ask_human" in body["brainstorm"] and "submit_design" in body["brainstorm"]
    assert "submit_plan" in body["plan"]
    assert "complete_step" in body["build_implement"]
    assert "submit_review" in body["build_step_review"]
    assert "submit_review" in body["review_final"]
    assert "report_finish" in body["finish"]
    for key, text in body.items():
        assert "<untrusted" in text, key
        if key != "finish":
            assert "docs/superpowers/specs" not in text, key


async def test_admin_edit_creates_new_version_and_audits(client, db):
    await methodology.seed_defaults(db)
    admin = await make_user(db, role=Role.admin)
    await db.commit()
    await login(client, admin)
    r = await client.put("/api/methodology/plan", json={"body_md": "new plan text"})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["body_md"] == "new plan text"
    assert (await methodology.current(db, "plan")).version == 2
    listed = {i["key"]: i for i in (await client.get("/api/methodology")).json()}
    assert len(listed) == 9 and listed["plan"]["version"] == 2 and listed["plan"]["stage"] == "plan"
    versions = (await client.get("/api/methodology/plan/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    old = await client.get("/api/methodology/plan/versions/1")
    assert old.status_code == 200 and old.json()["body_md"] != "new plan text"
    assert (await client.get("/api/methodology/plan/versions/9")).status_code == 404
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "methodology.updated"))).scalars().all()
    assert len(audit) == 1 and audit[0].data == {"key": "plan", "version": 2}


async def test_reviewers_cannot_ask_human_everyone_else_can(db):
    await methodology.seed_defaults(db)
    reviewers = {"build_step_review", "review_final"}
    for key in methodology.ALL_KEYS:
        text = (await methodology.current(db, key)).body_md
        assert ("ask_human" in text) is (key not in reviewers), key
    for key in reviewers:
        text = (await methodology.current(db, key)).body_md
        assert "changes_requested" in text and "important" in text and "submit_review" in text
    assert "complete_step" not in (await methodology.current(db, "review_fix")).body_md.replace(
        "Do not call `complete_step`", ""
    )


async def test_concurrent_edit_clash_is_409(client, db, monkeypatch):
    await methodology.seed_defaults(db)
    admin = await make_user(db, role=Role.admin)
    await db.commit()
    await login(client, admin)
    real = methodology.current

    async def stale(db_, key):  # another admin saved v2 between our read and our insert
        row = await real(db_, key)
        async with SessionLocal() as other:
            other.add(MethodologyVersion(key=key, version=row.version + 1, body_md="theirs"))
            await other.commit()
        return row

    monkeypatch.setattr(methodology, "current", stale)
    r = await client.put("/api/methodology/plan", json={"body_md": "mine"})
    assert r.status_code == 409 and r.json()["detail"] == "methodology_conflict"
    monkeypatch.setattr(methodology, "current", real)
    assert (await real(db, "plan")).body_md == "theirs"


async def test_lifespan_seeds_defaults(app, db, monkeypatch):
    monkeypatch.setattr("app.main.hub.start", _noop)
    monkeypatch.setattr("app.main.hub.stop", _noop)
    monkeypatch.setattr("app.main.hub.ready.wait", _noop)
    async with app.router.lifespan_context(app):
        pass
    assert await _count(db) == 9


async def _noop(*a, **k):
    return None


async def test_member_cannot_edit_403(client, db):
    await methodology.seed_defaults(db)
    member = await make_user(db)
    await db.commit()
    await login(client, member)
    assert (await client.get("/api/methodology")).status_code == 200
    assert (await client.put("/api/methodology/plan", json={"body_md": "x"})).status_code == 403
    assert await _count(db) == 9


async def test_unknown_key_404(client, db):
    admin = await make_user(db, role=Role.admin)
    await db.commit()
    await login(client, admin)
    assert (await client.put("/api/methodology/nope", json={"body_md": "x"})).status_code == 404
    assert (await client.get("/api/methodology/nope/versions")).status_code == 404
    assert (await client.get("/api/methodology/nope/versions/1")).status_code == 404
