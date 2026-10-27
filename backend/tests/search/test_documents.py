"""Index documents and reader tokens (Plan 9 Task 2): what each kind puts into the search index."""

import uuid

from sqlalchemy import insert, select

from app.a2a.models import Question
from app.agents.models import Agent, AgentBinding, AgentProgram
from app.auth.models import UserStatus
from app.kb import access as kb_access
from app.kb.models import KbDocument
from app.projects.models import BoardColumn, Label, Project
from app.search import documents
from app.tasks.models import Comment, Task, task_labels
from app.teams.models import TeamMember
from tests.factories import make_project, make_team, make_user


async def _project(client, db, key="PAY"):
    project, manager, team = await make_project(client, db, key)
    return await db.get(Project, uuid.UUID(project["id"])), manager, team


async def _column(db, project, category):
    return (
        await db.execute(
            select(BoardColumn).where(BoardColumn.project_id == project.id, BoardColumn.category == category).limit(1)
        )
    ).scalar_one()


async def _task(db, project, number=1, title="Retry failed card payments", category="working", **kw):
    col = await _column(db, project, category)
    task = Task(project_id=project.id, number=number, type="task", title=title, column_id=col.id, position=1.0, **kw)
    db.add(task)
    await db.commit()
    return task


async def test_task_document(client, db):
    project, manager, _ = await _project(client, db)
    task = await _task(db, project, description_md="Retry after 1, 5 and 30 minutes.", assignee_user_id=manager.id)
    label = Label(project_id=project.id, name="bug", color="#ff0000")
    db.add(label)
    await db.flush()
    await db.execute(insert(task_labels).values(task_id=task.id, label_id=label.id))
    db.add_all([Comment(task_id=task.id, author_user_id=manager.id, body_md="First comment"),
                Comment(task_id=task.id, author_user_id=manager.id, body_md="Second comment")])
    await db.commit()
    doc = await documents.build(db, "task", task.id)
    assert doc["id"] == f"task-{task.id}"
    assert {k: doc[k] for k in ("kind", "key", "title", "body", "url", "readers", "project_id", "project_key",
                                "status", "assignee", "type", "labels")} == {
        "kind": "task", "key": "PAY-1", "title": "Retry failed card payments",
        "body": "Retry after 1, 5 and 30 minutes.", "url": "/projects/PAY/board?task=PAY-1",
        "readers": [f"project:{project.id}"], "project_id": str(project.id), "project_key": "PAY",
        "status": "working", "assignee": f"user:{manager.id}", "type": "task", "labels": ["bug"],
    }
    assert "First comment" in doc["comments"] and "Second comment" in doc["comments"]
    assert isinstance(doc["updated_at"], int) and doc["updated_at"] > 0


async def test_task_comments_capped_at_20000_characters_newest_first(client, db):
    project, manager, _ = await _project(client, db)
    task = await _task(db, project)
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, tzinfo=UTC)
    db.add_all(Comment(task_id=task.id, author_user_id=manager.id, body_md=f"c{n:03d} " + "x" * 995,
                       created_at=base + timedelta(minutes=n)) for n in range(40))
    await db.commit()
    doc = await documents.build(db, "task", task.id)
    assert len(doc["comments"]) <= 20_000
    assert doc["comments"].startswith("c039") and "c000" not in doc["comments"]


async def test_documents_in_project_and_team_spaces(client, db):
    project, _, team = await _project(client, db)
    await kb_access.ensure_spaces(db)
    pspace = await kb_access.space_for_project(db, project.id)
    tspace = await kb_access.space_for_team(db, team.id)
    pdoc = KbDocument(space_id=pspace.id, title="Retry policy", body_md="Every call is retried.")
    tdoc = KbDocument(space_id=tspace.id, title="Team notes", body_md="Hello")
    db.add_all([pdoc, tdoc])
    await db.commit()
    p = await documents.build(db, "document", pdoc.id)
    assert (p["kind"], p["title"], p["body"], p["url"]) == ("document", "Retry policy", "Every call is retried.",
                                                           f"/kb/doc/{pdoc.id}")
    assert (p["readers"], p["project_id"], p["project_key"]) == ([f"space:{pspace.id}"], str(project.id), "PAY")
    t = await documents.build(db, "document", tdoc.id)
    assert (t["readers"], t["project_id"]) == ([f"space:{tspace.id}"], None)


async def test_project_team_person_agent_documents(client, db):
    project, manager, team = await _project(client, db)
    p = await documents.build(db, "project", project.id)
    assert (p["key"], p["title"], p["url"], p["readers"]) == ("PAY", "Project PAY", "/projects/PAY/board",
                                                              [f"project:{project.id}"])
    t = await documents.build(db, "team", team.id)
    assert (t["title"], t["url"], t["readers"]) == (team.name, f"/teams/{team.id}", ["all"])

    person = await documents.build(db, "person", manager.id)
    assert (person["title"], person["body"], person["url"], person["readers"]) == (
        manager.name, manager.email, None, ["all"])
    assert person["card"] == {"email": manager.email, "teams": [{"id": str(team.id), "name": team.name}]}
    gone = await make_user(db, status=UserStatus.deactivated)
    assert await documents.build(db, "person", gone.id) is None
    invited = await make_user(db, status=UserStatus.invited)
    assert await documents.build(db, "person", invited.id) is None

    agent = Agent(owner_id=manager.id, name="Ann's Codex", program=AgentProgram.codex)
    db.add(agent)
    await db.flush()
    db.add(AgentBinding(agent_id=agent.id, project_id=project.id, local_path="/x"))
    await db.commit()
    a = await documents.build(db, "agent", agent.id)
    assert (a["title"], a["body"], a["readers"], a["url"]) == ("Ann's Codex", manager.name, ["all"], None)
    assert a["card"] == {"owner_name": manager.name, "projects": [{"id": str(project.id), "key": "PAY"}]}


async def test_question_document_readers(client, db):
    target, _, _ = await _project(client, db, "QBB")
    source, _, _ = await _project(client, db, "QAA")
    task = await _task(db, source)
    asker = await make_user(db)
    q = Question(target_project_id=target.id, number=1, from_task_id=task.id, asked_by_user_id=asker.id,
                 title="How do refunds work?", body="Details please", status="answered",
                 answer_md="Through the refunds service.")
    db.add(q)
    await db.commit()
    doc = await documents.build(db, "question", q.id)
    assert (doc["key"], doc["title"], doc["url"]) == ("QBB-Q1", "How do refunds work?", f"/questions/{q.id}")
    assert "Details please" in doc["body"] and "Through the refunds service." in doc["body"]
    assert sorted(doc["readers"]) == sorted([f"project:{target.id}", f"project:{source.id}", f"user:{asker.id}"])
    assert (doc["project_id"], doc["project_key"]) == (str(target.id), "QBB")


async def test_missing_items_build_none(db):
    for kind in documents.KINDS:
        assert await documents.build(db, kind, uuid.uuid4()) is None, kind


async def test_ids_of_lists_every_indexable_item(client, db):
    project, manager, team = await _project(client, db)
    task = await _task(db, project)
    member = await make_user(db)
    db.add(TeamMember(team_id=team.id, user_id=member.id))
    await make_user(db, status=UserStatus.deactivated)
    await make_team(db)
    await db.commit()
    assert [i async for i in documents.ids_of(db, "task")] == [task.id]
    people = {i async for i in documents.ids_of(db, "person")}
    assert {manager.id, member.id} <= people and len(people) == 2
