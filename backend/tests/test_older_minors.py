"""Fixes for small issues left from earlier plans: tokens after a password reset, the forgot-password timing, email
subjects, a limit of 0, the database password, duplicate emails, deleting a team of archived projects, and closing a
project while a workflow finishes."""

import uuid

import pytest
from sqlalchemy import select

from app.auth.models import Role
from app.core.config import Settings
from app.core.email import SmtpMailer
from app.org.models import OrgSettings
from app.projects import lifecycle
from app.projects.models import Project
from app.ratelimit import store
from app.ratelimit.limits import Limit
from app.tasks.models import Task
from app.teams.models import Team
from app.workflow.models import TaskWorkflow
from tests.factories import login, make_project, make_user


def _token_from(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


async def test_password_reset_also_revokes_api_tokens(client, client_factory, db, outbox):
    """Someone who learned the password may have made tokens: recovering the account ends them too."""
    u = await make_user(db, email="r@x.io")
    await login(client, u)
    r = await client.post("/api/tokens", json={"name": "laptop", "scopes": ["runner"]})
    assert r.status_code == 201, r.text
    other = client_factory()
    assert (await other.post("/api/auth/forgot", json={"email": "r@x.io"})).status_code == 204
    url = next(w for w in outbox.sent[0][2].split() if "/reset/" in w)
    r = await other.post("/api/auth/reset", json={"token": _token_from(url), "password": "fresh-pass-12"})
    assert r.status_code == 204, r.text
    from app.auth.models import PersonalAccessToken

    revoked = await db.scalar(select(PersonalAccessToken.revoked_at).where(PersonalAccessToken.user_id == u.id)
                              .execution_options(populate_existing=True))
    assert revoked is not None


async def test_forgot_password_answers_before_the_email_is_sent(app, db, outbox):
    """A known address must not answer slower than an unknown one: the email goes out after the response."""
    await make_user(db, email="known@x.io")
    events: list[str] = []
    real_send = outbox.send

    async def send(to, subject, body):
        events.append("email")
        await real_send(to, subject, body)

    outbox.send = send
    body = b'{"email": "known@x.io"}'
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/auth/forgot", "raw_path": b"/api/auth/forgot", "query_string": b"", "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()), (b"x-megoo-client", b"web")],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
    }
    sent_body = False

    async def receive():
        nonlocal sent_body
        if sent_body:
            return {"type": "http.disconnect"}
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send_asgi(message):
        if message["type"] == "http.response.start":
            events.append(f"response {message['status']}")

    await app(scope, receive, send_asgi)
    assert events == ["response 204", "email"]


async def test_a_newline_in_a_subject_cannot_break_the_email(monkeypatch):
    sent = []

    async def fake_send(msg, **_kw):
        sent.append(msg)

    monkeypatch.setattr("app.core.email.aiosmtplib.send", fake_send)
    mailer = SmtpMailer(OrgSettings(smtp_host="mail.example", smtp_from="m@example"))
    await mailer.send("u@example", "[MegooColab] Pat\nEvil-Header: x\r\nmentioned you", "body")
    assert sent[0]["Subject"] == "[MegooColab] Pat Evil-Header: x mentioned you"
    assert sent[0]["Evil-Header"] is None


async def test_a_limit_of_zero_means_off():
    off = Limit("off", max=0, window=60)
    s = f"s-{uuid.uuid4()}"
    assert all([(await store.hit(off, s)).allowed for _ in range(5)])
    assert (await store.peek(off, s)).allowed


@pytest.mark.parametrize("password", ["p@ss:w/rd", "100%sure#", "a b?c&d"])
def test_database_password_with_special_characters(password):
    """POSTGRES_PASSWORD is any text: it goes into the database URL encoded, and alembic gets it escaped."""
    from sqlalchemy.engine import make_url

    from app.core.config import alembic_url

    s = Settings(secret_key="x" * 64, database_url="postgresql+asyncpg://megoo@db:5432/megoo",
                 postgres_password=password)
    url = make_url(s.database_url)
    assert (url.username, url.password, url.host, url.port, url.database) == ("megoo", password, "db", 5432, "megoo")
    from configparser import ConfigParser

    parser = ConfigParser()
    parser.add_section("a")
    parser.set("a", "url", alembic_url(s.database_url))
    assert make_url(parser.get("a", "url")).password == password


def test_database_url_with_its_own_password_is_left_alone():
    s = Settings(secret_key="x" * 64, database_url="postgresql+asyncpg://megoo:megoo@localhost:5433/megoo")
    assert s.database_url == "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo"


async def test_two_admins_adding_the_same_email_get_409_not_500(client, db, monkeypatch):
    """The check before the insert can race: the database's unique email decides, and says email_taken."""
    from app.users import router as users_router

    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    await make_user(db, email="same@x.io")

    async def raced(_db, _email):  # the other request inserted after this one checked
        return None

    monkeypatch.setattr(users_router, "_ensure_email_free", raced)
    r = await client.post("/api/admin/users/invite", json={"email": "same@x.io", "name": "S", "role": "member"})
    assert (r.status_code, r.json()["detail"]) == (409, "email_taken")
    r = await client.post("/api/admin/users", json={"email": "same@x.io", "name": "S", "role": "member",
                                                    "temporary_password": "temp-pass-123"})
    assert (r.status_code, r.json()["detail"]) == (409, "email_taken")


async def test_a_team_whose_projects_are_all_archived_can_be_deleted(client, db):
    _p, _manager, team = await make_project(client, db, "PAY")  # signed in as its manager
    detail = (await client.get(f"/api/teams/{team.id}")).json()
    assert detail["blocking_project_count"] == 1
    assert (await client.put("/api/projects/PAY/status", json={"status": "finished"})).status_code == 200
    assert (await client.delete(f"/api/teams/{team.id}")).status_code == 409  # finished projects still count
    assert (await client.put("/api/projects/PAY/status", json={"status": "archived"})).status_code == 200
    detail = (await client.get(f"/api/teams/{team.id}")).json()
    assert (detail["project_count"], detail["blocking_project_count"]) == (1, 0)
    assert (await client.delete(f"/api/teams/{team.id}")).status_code == 204
    assert await db.get(Team, team.id, populate_existing=True) is None
    assert (await db.scalar(select(Project.status).where(Project.key == "PAY"))) == "archived"  # kept, teamless


async def test_closing_skips_a_workflow_that_finished_meanwhile(client, db, monkeypatch):
    """Between listing the workflows to pause and pausing them, one may finish: the close goes on without it."""
    await make_project(client, db, "PAY")
    r = await client.post("/api/projects/PAY/tasks", json={"title": "done already", "type": "task"})
    task_id = uuid.UUID(r.json()["id"])
    db.add(TaskWorkflow(task_id=task_id, driver="runner", stage="done", status="finished"))
    await db.commit()

    async def stale(session, _project_id):  # listed while it was still running
        return [await session.get(Task, task_id)]

    monkeypatch.setattr(lifecycle, "active_workflow_tasks", stale)
    r = await client.put("/api/projects/PAY/status", json={"status": "finished"})
    assert r.status_code == 200, r.text
    assert (await db.get(TaskWorkflow, task_id, populate_existing=True)).status == "finished"
