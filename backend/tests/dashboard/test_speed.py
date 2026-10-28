"""The home page must stay quick: under 300 ms with 10,000 tasks."""

import time

from sqlalchemy import text

from tests.dashboard.conftest import column_id
from tests.factories import login

# 10,000 tasks over PAY's columns: every fifth done in the last 14 days, every tenth due (some overdue), every
# seventh assigned to the viewer and every eleventh to the viewer's agent
BULK_INSERT = text("""
INSERT INTO tasks (id, project_id, number, type, title, description_md, column_id, position, priority,
                   due_date, assignee_user_id, assignee_agent_id, completed_at, created_at, updated_at)
SELECT gen_random_uuid(), CAST(:project AS uuid), 1000 + n, (ARRAY['task','story','bug','subtask'])[1 + n % 4], 'Task ' || n, '',
       CAST(CASE WHEN n % 5 = 0 THEN :done WHEN n % 3 = 0 THEN :working ELSE :before END AS uuid), n, 'medium',
       CASE WHEN n % 10 = 0 THEN current_date + (n % 21 - 10) END,
       CASE WHEN n % 7 = 0 AND n % 11 <> 0 THEN CAST(:viewer AS uuid) END,
       CASE WHEN n % 11 = 0 THEN CAST(:agent AS uuid) END,
       CASE WHEN n % 5 = 0 THEN now() - (n % 14) * interval '1 day' END, now(), now()
FROM generate_series(1, 10000) AS n
""")


async def test_dashboard_answers_under_300ms_with_10k_tasks(client, db, world):
    await db.execute(BULK_INSERT, {
        "project": str(world.pay.id), "done": str(await column_id(db, world.pay, "done")),
        "working": str(await column_id(db, world.pay, "working")),
        "before": str(await column_id(db, world.pay, "before")),
        "viewer": str(world.viewer.id), "agent": str(world.agent.id),
    })
    await db.commit()
    await db.execute(text("ANALYZE tasks"))
    await login(client, world.admin)
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        r = await client.get("/api/dashboard", params={"scope": "all"})
        timings.append(time.perf_counter() - start)
        assert r.status_code == 200, r.text
    assert r.json()["numbers"]["open_tasks"] > 0
    assert min(timings) < 0.3, timings
