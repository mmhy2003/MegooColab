"""Recent activity: the latest task events in scope, worded like a task's own activity list."""

from app.projects.models import BoardColumn
from app.tasks.models import TaskEvent
from tests.dashboard.conftest import add_task, column_id, dash, task_key
from tests.factories import login


async def test_activity_is_the_eight_latest_task_events_without_streamed_updates(client, db, world):
    task = await add_task(db, world.pay)
    working = await column_id(db, world.pay, "working")
    working_name = (await db.get(BoardColumn, working)).name
    for kind, data, actor in [("created", {}, world.viewer.id),
                              ("status_changed", {"to_column": str(working)}, world.viewer.id),
                              ("agent_message", {"text": "hi"}, None), ("question.asked", {}, None),
                              ("agent_run_completed", {"agent_id": str(world.agent.id)}, None)]:
        db.add(TaskEvent(task_id=task.id, kind=kind, data=data, actor_user_id=actor))
        await db.commit()
    db.add(TaskEvent(task_id=(await add_task(db, world.web)).id, kind="created", data={}))
    await db.commit()
    await login(client, world.viewer)
    rows = (await dash(client))["activity"]
    assert [r["kind"] for r in rows] == ["agent_run_completed", "status_changed", "created"]
    assert rows[0]["actor_name"] == "Viewer bot" and rows[1]["actor_name"] == world.viewer.name
    assert rows[1]["names"] == {str(working): working_name} and rows[1]["task_key"] == task_key(task)


async def test_activity_stops_at_eight(client, db, world):
    task = await add_task(db, world.pay)
    for _ in range(10):
        db.add(TaskEvent(task_id=task.id, kind="created", data={}))
    await db.commit()
    await login(client, world.viewer)
    assert len((await dash(client))["activity"]) == 8
