"""Settings › Repositories: a repository shows the most recent problem reading its pull requests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.crypto import encrypt
from app.git.models import GitConnection, TaskPullRequest
from app.projects.models import BoardColumn, Project, ProjectRepository
from app.tasks.models import Task
from tests.factories import make_project

NOW = datetime.now(UTC)


async def _world(client, db):
    await make_project(client, db, "PAY")
    project = (await db.execute(select(Project).where(Project.key == "PAY"))).scalar_one()
    conn = GitConnection(name="GitHub", kind="github", base_url="https://github.com", token_enc=encrypt("t"))
    db.add(conn)
    await db.flush()
    repo = ProjectRepository(project_id=project.id, name="acme/pay", url="https://github.com/acme/pay",
                             provider="github", connection_id=conn.id)
    db.add(repo)
    await db.commit()
    return project, conn


async def _pr(db, project, conn, n, url, *, error=None, limited=None, checked=None):
    col = (await db.execute(select(BoardColumn).where(BoardColumn.project_id == project.id))).scalars().first()
    t = Task(project_id=project.id, number=900 + n, type="task", title=f"t{n}", column_id=col.id, position=float(n))
    db.add(t)
    await db.flush()
    db.add(TaskPullRequest(task_id=t.id, url=url, connection_id=conn.id, state="open", error=error, limited=limited,
                           last_checked_at=checked))
    await db.commit()


async def _repo_json(client):
    r = await client.get("/api/projects/PAY/repositories")
    assert r.status_code == 200, r.text
    return r.json()[0]


async def test_repo_shows_the_latest_pr_read_problem(client, db):
    project, conn = await _world(client, db)
    await _pr(db, project, conn, 1, "https://github.com/acme/pay/pull/1", checked=NOW - timedelta(hours=2))
    await _pr(db, project, conn, 2, "https://github.com/acme/pay/pull/2", error="forbidden", limited="checks",
              checked=NOW)
    out = await _repo_json(client)
    assert (out["pr_error"], out["pr_limited"]) == ("forbidden", "checks")


async def test_a_clean_newer_read_clears_the_problem(client, db):
    project, conn = await _world(client, db)
    await _pr(db, project, conn, 1, "https://github.com/acme/pay/pull/1", error="forbidden",
              checked=NOW - timedelta(hours=2))
    await _pr(db, project, conn, 2, "https://github.com/acme/pay/pull/2", checked=NOW)
    out = await _repo_json(client)
    assert (out["pr_error"], out["pr_limited"]) == (None, None)


async def test_another_repositorys_rows_are_ignored(client, db):
    project, conn = await _world(client, db)
    await _pr(db, project, conn, 1, "https://github.com/acme/other/pull/1", error="forbidden", checked=NOW)
    out = await _repo_json(client)
    assert out["pr_error"] is None


async def test_branch_mismatch_is_not_a_read_problem_and_unread_rows_do_not_win(client, db):
    project, conn = await _world(client, db)
    await _pr(db, project, conn, 1, "https://github.com/acme/pay/pull/1", error="forbidden",
              checked=NOW - timedelta(hours=1))
    await _pr(db, project, conn, 2, "https://github.com/acme/pay/pull/2", error="not_found", checked=None)
    assert (await _repo_json(client))["pr_error"] == "forbidden"
    await _pr(db, project, conn, 3, "https://github.com/acme/pay/pull/3", error="branch_mismatch", checked=NOW)
    assert (await _repo_json(client))["pr_error"] is None
