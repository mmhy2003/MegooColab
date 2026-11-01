"""Chat rounds stay off the board, out of counts, reports, recent activity, search and MCP."""

import uuid

from app.search.documents import _task
from app.tasks.models import Task
from tests.chats.helpers import start, world


async def _round(client, db) -> tuple[dict, dict]:
    await world(client, db)
    before = (await client.get("/api/dashboard")).json()
    chat = await start(client)
    return chat, before


async def test_board_backlog_and_sprints_skip_chat_rounds(client, db):
    chat, _ = await _round(client, db)
    key = chat["rounds"][0]["key"]
    for params in ({}, {"sprint": "backlog"}, {"q": "empty email"}):
        tasks = (await client.get("/api/projects/PAY/tasks", params=params)).json()
        assert all(t["key"] != key for t in tasks), params


async def test_column_counts_skip_chat_rounds(client, db):
    await _round(client, db)
    columns = (await client.get("/api/projects/PAY/columns")).json()
    assert sum(c["task_count"] for c in columns) == 0


async def test_dashboard_numbers_skip_chat_rounds(client, db):
    _, before = await _round(client, db)
    after = (await client.get("/api/dashboard")).json()
    for k in ("open_tasks", "workflows_in_progress", "open_in_progress"):
        assert after["numbers"][k] == before["numbers"][k], k
    assert after["stages"] == before["stages"]


async def test_search_never_indexes_a_chat_round(client, db):
    chat, _ = await _round(client, db)
    task_id = (await client.get(f"/api/tasks/{chat['rounds'][0]['key']}")).json()["id"]
    assert await _task(db, uuid.UUID(task_id)) is None
    assert (await db.get(Task, uuid.UUID(task_id))).in_chat


async def test_mcp_list_tasks_skips_chat_rounds(client, db):
    chat, _ = await _round(client, db)
    from app.projects.models import Project
    from app.tasks.service import list_tasks

    project = (await db.execute(Project.__table__.select().where(Project.key == "PAY"))).first()
    tasks = await list_tasks(db, await db.get(Project, project.id))
    assert all(t.number != int(chat["rounds"][0]["key"].split("-")[1]) for t in tasks)


async def test_a_chat_rounds_activity_is_not_in_recent_activity(client, db):
    chat, _ = await _round(client, db)
    rows = (await client.get("/api/dashboard")).json()["activity"]
    assert all(chat["rounds"][0]["key"] not in str(r) for r in rows)
