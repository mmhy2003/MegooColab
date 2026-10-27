"""Admin settings (ADM-1): the dreaming schedule and the defaults new projects take."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.memory import dream
from app.projects.models import Project
from tests.factories import login, make_team, make_user
from tests.org.test_org_settings import SMTP, _setup_org

DEFAULTS = {"finishing_option": "keep_branch", "require_human_code_review": True, "sprints_enabled": False,
            "commit_docs_to_repo": True}


async def _admin(client, db):
    await _setup_org(db)
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    return admin


async def test_settings_round_trip_and_validation(client, db):
    await _admin(client, db)
    body = (await client.get("/api/admin/settings")).json()
    assert body["dreaming"] == {"enabled": True, "hour_utc": None}
    assert body["project_defaults"] == {"finishing_option": "pull_request", "require_human_code_review": False,
                                        "sprints_enabled": True, "commit_docs_to_repo": False}
    r = await client.put("/api/admin/settings", json={"name": "Acme", "smtp": SMTP,
                                                      "dreaming": {"enabled": False, "hour_utc": 5},
                                                      "project_defaults": DEFAULTS})
    assert r.status_code == 200, r.text
    assert r.json()["dreaming"] == {"enabled": False, "hour_utc": 5} and r.json()["project_defaults"] == DEFAULTS
    bad = await client.put("/api/admin/settings", json={"name": "Acme", "smtp": SMTP,
                                                        "dreaming": {"enabled": True, "hour_utc": 24}})
    assert bad.status_code == 422
    # leaving the new sections out keeps them (the older settings page sends name and smtp only)
    await client.put("/api/admin/settings", json={"name": "Acme 2", "smtp": SMTP})
    body = (await client.get("/api/admin/settings")).json()
    assert body["name"] == "Acme 2" and body["dreaming"]["hour_utc"] == 5 and body["project_defaults"] == DEFAULTS
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "org.settings_changed"))).scalars().all()


async def test_new_project_takes_org_defaults(client, db):
    admin = await _admin(client, db)
    team = await make_team(db, admin)
    old = await client.post("/api/projects", json={"key": "OLD", "name": "Old", "team_ids": [str(team.id)]})
    assert old.status_code == 201
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": SMTP, "project_defaults": DEFAULTS})
    r = await client.post("/api/projects", json={"key": "NEW", "name": "New", "team_ids": [str(team.id)]})
    assert r.status_code == 201, r.text
    new = (await db.execute(select(Project).where(Project.key == "NEW"))).scalar_one()
    assert (new.finishing_option, new.require_human_code_review, new.sprints_enabled, new.commit_docs_to_repo) == (
        "keep_branch", True, False, True)
    old_row = (await db.execute(select(Project).where(Project.key == "OLD"))).scalar_one()
    assert (old_row.finishing_option, old_row.sprints_enabled) == ("pull_request", True)  # unchanged


async def _ticks(monkeypatch, hour: int) -> int:
    monkeypatch.setattr(dream, "utcnow", lambda: datetime(2026, 10, 27, hour, 5, tzinfo=UTC))
    async with SessionLocal() as s:
        await dream.dream_tick(s, {})
        await s.commit()
        return len((await s.execute(select(Job).where(Job.kind == "mem.dream"))).scalars().all())


async def test_dream_tick_respects_enabled_and_hour(client, db, monkeypatch):
    await _admin(client, db)
    setting = get_settings().memory_dream_hour_utc
    assert await _ticks(monkeypatch, (setting + 1) % 24) == 0
    assert await _ticks(monkeypatch, setting) == 1  # no org hour: the server setting
    async with SessionLocal() as s:
        await s.execute(Job.__table__.delete())
        await s.commit()
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": SMTP,
                                                  "dreaming": {"enabled": True, "hour_utc": (setting + 2) % 24}})
    assert await _ticks(monkeypatch, setting) == 0
    assert await _ticks(monkeypatch, (setting + 2) % 24) == 1  # the org hour wins
    async with SessionLocal() as s:
        await s.execute(Job.__table__.delete())
        await s.commit()
    await client.put("/api/admin/settings", json={"name": "Acme", "smtp": SMTP,
                                                  "dreaming": {"enabled": False, "hour_utc": (setting + 2) % 24}})
    assert await _ticks(monkeypatch, (setting + 2) % 24) == 0  # disabled: never scheduled
