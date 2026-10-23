"""Run updates become metadata-only task events (BRD NFR-2)."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import apply_update, finish_run, sanitize_update
from app.tasks.models import TaskEvent
from tests.agent_runs.test_dispatch import (  # noqa: F401  (tc_factory is a fixture)
    URL,
    _avail,
    _hello,
    _offline_runs,
    _setup,
    _start,
    _task,
    _wait_run,
    tc_factory,
)
from tests.factories import make_user
from tests.runner.test_runner_ws import _manager_with_project


async def _running(client, db, n=1):
    me, agent, runs = await _offline_runs(client, db, n=n)
    await db.execute(update(AgentRun).values(status="running"))
    await db.commit()
    return me, agent, [uuid.UUID(r["id"]) for r in runs]


async def _events(db, prefix="agent_") -> list[TaskEvent]:
    """Events of the given kind prefix; the default is run updates (not the run_* lifecycle events)."""
    rows = await db.execute(
        select(TaskEvent).order_by(TaskEvent.created_at, TaskEvent.id).execution_options(populate_existing=True)
    )
    return [
        e
        for e in rows.scalars()
        if e.kind.startswith(prefix) and e.kind != "agent_run_queued"
        and (prefix != "agent_" or not e.kind.startswith("agent_run_"))
    ]


async def _row(db, run_id) -> AgentRun:
    return (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id).execution_options(populate_existing=True))
    ).scalar_one()


async def test_update_becomes_task_event_visible_in_activity(client, db):
    me, agent, [run_id] = await _running(client, db)
    await apply_update(db, me.id, run_id, 1, "tool", {"tool_kind": "read", "title": "Read a.py", "status": "completed"})
    await db.commit()
    assert (await _row(db, run_id)).last_seq == 1
    task_key = (await client.get("/api/projects/PAY/tasks")).json()[0]["key"]
    items = (await client.get(f"/api/tasks/{task_key}/activity")).json()
    ev = next(i for i in items if i["kind"] == "agent_tool")
    assert ev["actor"] is None
    assert ev["data"] == {
        "tool_kind": "read", "title": "Read a.py", "status": "completed",
        "run_id": str(run_id), "agent_id": agent["id"],
    }


async def test_unknown_kind_dropped(client, db):
    me, _agent, [run_id] = await _running(client, db)
    assert sanitize_update("shell_dump", {"text": "x"}) is None
    await apply_update(db, me.id, run_id, 1, "shell_dump", {"text": "x"})
    await db.commit()
    assert await _events(db) == []


async def test_extra_fields_like_content_or_diff_are_stripped(client, db):
    me, agent, [run_id] = await _running(client, db)
    data = {
        "path": "src/a.py", "lines_added": 3, "lines_removed": 1,
        "content": "secret code", "diff": "+secret", "old_text": "x",
    }
    await apply_update(db, me.id, run_id, 1, "file_change", data)
    await db.commit()
    [ev] = await _events(db)
    assert ev.kind == "agent_file_change"
    assert ev.data == {
        "path": "src/a.py", "lines_added": 3, "lines_removed": 1,
        "run_id": str(run_id), "agent_id": agent["id"],
    }


def test_other_kinds_keep_only_allowed_fields_and_limits():
    assert sanitize_update("command", {"command": "pytest -q tests/ --secret", "exit_code": 1, "output": "boom"}) == {
        "command": "pytest", "exit_code": 1,
    }
    plan = sanitize_update(
        "plan",
        {"entries": [{"title": "t" * 300, "status": "in_progress", "body": "x"}] * 60, "x": 1},
    )
    assert len(plan["entries"]) == 50
    assert plan["entries"][0] == {"title": "t" * 200, "status": "in_progress"}
    perm = sanitize_update(
        "permission",
        {"tool_kind": "edit", "title": "Edit", "decision": "denied", "reason": "r" * 500, "raw_input": {"a": 1}},
    )
    assert perm == {"tool_kind": "edit", "title": "Edit", "decision": "denied", "reason": "r" * 200}
    assert sanitize_update("tool", {"tool_kind": "read", "title": "x", "status": "completed", "output": "o"}) == {
        "tool_kind": "read", "title": "x", "status": "completed",
    }


async def test_message_truncated_to_4000(client, db):
    me, _agent, [run_id] = await _running(client, db)
    await apply_update(db, me.id, run_id, 1, "message", {"text": "a" * 10_000})
    await db.commit()
    [ev] = await _events(db)
    assert ev.data["text"] == "a" * 4000


async def test_absolute_or_parent_paths_redacted(client, db):
    for bad in ("/etc/passwd", "../../etc/x", "a/../../b", "C:\\Users\\me\\x", "C:/x", "\\\\srv\\share", "a\\..\\b"):
        assert sanitize_update("file_change", {"path": bad})["path"] == "<outside worktree>", bad
    assert sanitize_update("file_change", {"path": "src/a..b/c.py"})["path"] == "src/a..b/c.py"
    me, _agent, [run_id] = await _running(client, db)
    await apply_update(db, me.id, run_id, 1, "file_change", {"path": "/etc/passwd", "lines_added": 1, "lines_removed": 0})
    await db.commit()
    [ev] = await _events(db)
    assert ev.data["path"] == "<outside worktree>"


async def test_duplicate_seq_ignored(client, db):
    me, _agent, [run_id] = await _running(client, db)
    # one transaction per update, as on the socket: events written in one transaction share created_at
    for seq, text in ((2, "one"), (2, "again"), (1, "older"), (3, "two")):
        await apply_update(db, me.id, run_id, seq, "message", {"text": text})
        await db.commit()
    assert [e.data["text"] for e in await _events(db)] == ["one", "two"]
    assert (await _row(db, run_id)).last_seq == 3


async def test_update_for_someone_elses_run_ignored(client, db):
    _me, _agent, [run_id] = await _running(client, db)
    stranger = await make_user(db)
    await apply_update(db, stranger.id, run_id, 1, "message", {"text": "hi"})
    await db.commit()
    assert await _events(db) == []
    assert (await _row(db, run_id)).last_seq == 0


async def test_update_ignored_unless_running(client, db):
    me, _agent, runs = await _offline_runs(client, db)  # queued
    await apply_update(db, me.id, uuid.UUID(runs[0]["id"]), 1, "message", {"text": "hi"})
    await db.commit()
    assert await _events(db) == []


async def test_finish_records_summary_and_dispatches_next(client, db):
    me, agent, [first, second] = await _running(client, db, n=2)
    await db.execute(update(AgentRun).where(AgentRun.id == second).values(status="queued", started_at=None))
    await db.commit()
    await finish_run(db, me.id, first, "completed", "All done", None)
    run = await _row(db, first)
    assert run.status == "completed" and run.summary == "All done" and run.finished_at is not None
    [ev] = await _events(db, "agent_run_")
    assert ev.kind == "agent_run_completed" and ev.actor_user_id is None
    assert ev.data == {"run_id": str(first), "agent_id": agent["id"], "summary": "All done"}
    # no runner is connected here, so the next run stays queued; real dispatch is covered by the socket test
    assert (await _row(db, second)).status == "queued"


async def test_finish_keeps_cancelled_and_terminal_states(client, db):
    me, _agent, [a, b] = await _running(client, db, n=2)
    await db.execute(update(AgentRun).where(AgentRun.id == a).values(status="cancelled", reason="user_deactivated"))
    await db.commit()
    await finish_run(db, me.id, a, "completed", "late", None)
    run = await _row(db, a)
    assert run.status == "cancelled" and run.summary == "late" and run.finished_at is not None
    assert await _events(db, "agent_run_") == []
    await finish_run(db, me.id, b, "failed", "broke", "boom")
    assert (await _row(db, b)).status == "failed"
    await finish_run(db, me.id, b, "completed", "again", None)  # a terminal run stays as it is
    again = await _row(db, b)
    assert again.status == "failed" and again.summary == "broke"


async def test_finish_for_someone_elses_run_ignored(client, db):
    _me, _agent, [run_id] = await _running(client, db)
    stranger = await make_user(db)
    await finish_run(db, stranger.id, run_id, "completed", "x", None)
    assert (await _row(db, run_id)).status == "running"


async def test_run_messages_over_socket_and_next_run_dispatched(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    second_task = _task(tc, agent, title="Second")
    first, second = _start(tc, task), _start(tc, second_task)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == first["id"]
        _wait_run(tc, task, first["id"], "running")
        ws.send_json({"type": "run_update", "run_id": first["id"], "seq": 1, "kind": "message", "data": {"text": "hi"}})
        ws.send_json({"type": "run_finished", "run_id": first["id"], "outcome": "completed", "summary": "ok"})
        assert ws.receive_json()["run_id"] == second["id"]
    items = tc.get(f"/api/tasks/{task['key']}/activity").json()
    kinds = [i["kind"] for i in items if i["type"] == "event"]
    assert "agent_message" in kinds and "agent_run_completed" in kinds
    _wait_run(tc, task, first["id"], "completed")


async def test_hello_fails_running_runs_not_on_this_connection(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    orphan = _start(tc, task)
    await db.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(orphan["id"])).values(status="running"))
    await db.commit()
    other = _task(tc, agent, title="Other")
    queued = _start(tc, other)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.receive_json()
        ws.send_json(_hello([_avail(agent)]))
        assert ws.receive_json()["run_id"] == queued["id"]  # dispatch happens after the orphan is failed
        _wait_run(tc, task, orphan["id"], "failed")
        assert tc.get(f"/api/tasks/{task['key']}/agent-runs").json()[0]["reason"] == "runner_disconnected"
        ws.send_json(_hello([_avail(agent)]))  # a second hello leaves this connection's own run alone
        ws.send_json({"type": "heartbeat"})
        _wait_run(tc, other, queued["id"], "running")
    kinds = [e.kind for e in await _events(db, "agent_run_")]
    assert "agent_run_failed" in kinds
