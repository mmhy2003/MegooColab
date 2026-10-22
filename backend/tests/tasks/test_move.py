from sqlalchemy import select

from app.tasks.models import TaskEvent
from app.tasks.ordering import needs_rebalance, position_between
from tests.factories import make_project


def test_position_between_cases():
    assert position_between(None, None) == 1024.0
    assert position_between(1024.0, None) == 2048.0
    assert position_between(None, 1024.0) == 0.0
    assert position_between(1024.0, 2048.0) == 1536.0
    assert needs_rebalance(1.0, 1.0 + 1e-7) is True
    assert needs_rebalance(1.0, 2.0) is False


async def _setup(client, db):
    await make_project(client, db)
    cols = {c["name"]: c for c in (await client.get("/api/projects/PAY/columns")).json()}
    keys = []
    for t in "abc":
        r = await client.post("/api/projects/PAY/tasks", json={"title": t, "type": "task", "column_id": cols["To Do"]["id"]})
        keys.append(r.json()["key"])
    return cols, keys


async def _column_order(client, column_id):
    tasks = (await client.get("/api/projects/PAY/tasks", params={"column": column_id})).json()
    return [t["title"] for t in sorted(tasks, key=lambda t: t["position"])]


async def test_move_between_two_cards_orders_correctly(client, db):
    cols, (a, b, c) = await _setup(client, db)
    r = await client.post(f"/api/tasks/{c}/move", json={"column_id": cols["To Do"]["id"], "before_key": a, "after_key": b})
    assert r.status_code == 200
    assert await _column_order(client, cols["To Do"]["id"]) == ["a", "c", "b"]
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["To Do"]["id"], "before_key": b})
    assert await _column_order(client, cols["To Do"]["id"]) == ["c", "b", "a"]
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["To Do"]["id"], "after_key": c})
    assert await _column_order(client, cols["To Do"]["id"]) == ["a", "c", "b"]


async def test_move_to_other_column_and_records_event(client, db):
    cols, (a, _, _) = await _setup(client, db)
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["In Progress"]["id"]})
    assert r.json()["column_category"] == "working"
    assert await _column_order(client, cols["In Progress"]["id"]) == ["a"]
    kinds = (await db.execute(select(TaskEvent.kind, TaskEvent.data))).all()
    moved = [d for k, d in kinds if k == "status_changed"]
    assert moved == [{"from_column": cols["To Do"]["id"], "to_column": cols["In Progress"]["id"], "to_category": "working"}]


async def test_move_into_done_sets_completed_at_and_out_clears_it(client, db):
    cols, (a, _, _) = await _setup(client, db)
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["Done"]["id"]})
    assert r.json()["completed_at"] is not None
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["In Review"]["id"]})
    assert r.json()["completed_at"] is None


async def test_move_neighbor_from_other_column_422(client, db):
    cols, (a, b, _) = await _setup(client, db)
    r = await client.post(f"/api/tasks/{a}/move", json={"column_id": cols["Done"]["id"], "before_key": b})
    assert r.status_code == 422


async def test_many_moves_trigger_rebalance_and_keep_order(client, db):
    cols, (a, b, c) = await _setup(client, db)
    todo = cols["To Do"]["id"]
    # repeatedly drop the bottom card between the top two; the gap halves each time
    order = ["a", "b", "c"]
    keys = {"a": a, "b": b, "c": c}
    for _ in range(60):
        moving = order[-1]
        above, below = order[0], order[1]
        r = await client.post(f"/api/tasks/{keys[moving]}/move", json={"column_id": todo, "before_key": keys[above], "after_key": keys[below]})
        assert r.status_code == 200
        order = [above, moving, below]
    assert await _column_order(client, todo) == order
    positions = sorted(t["position"] for t in (await client.get("/api/projects/PAY/tasks", params={"column": todo})).json())
    assert all(not needs_rebalance(x, y) for x, y in zip(positions, positions[1:]))
