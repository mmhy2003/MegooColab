"""The prompt section "Other projects you can ask" and the answers a resumed session is handed."""

import uuid
from types import SimpleNamespace

from sqlalchemy import select, update

from app.a2a import context as a2a_ctx
from app.a2a.models import Question, QuestionStatus
from app.chats.models import Chat
from app.projects.models import Project, ProjectStatus
from app.tasks.models import Comment, Task
from app.workflow.models import RunRole
from tests.factories import login, make_project, make_user

HEADING = "## Other projects you can ask"


async def _world(client, db, *, description="Fix the login"):
    """ASK (the task's project), with ANS and OLD (archived) visible to the task's person, and HID not."""
    me = await make_user(db, name="Me")
    for key in ("ASK", "ANS", "OLD"):
        await make_project(client, db, key, me)
    await make_project(client, db, "HID")
    await db.execute(update(Project).where(Project.key == "ANS").values(
        name="Answers", description="The customer web app <b>login</b>\nand live sessions " + "x" * 300))
    await db.execute(update(Project).where(Project.key == "OLD").values(status=ProjectStatus.archived))
    await db.commit()
    await login(client, me)
    r = await client.post("/api/projects/ASK/tasks", json={"title": "Task", "description_md": description})
    assert r.status_code == 201, r.text
    task = await db.get(Task, uuid.UUID(r.json()["id"]))
    task.assignee_user_id = me.id
    await db.commit()
    return me, task


async def _section(db, task, role=RunRole.implement):
    return await a2a_ctx.projects_context(db, task, role)


def _line(section: str, key: str) -> str:
    return next(ln for ln in section.splitlines() if ln.startswith(f"- {key} — "))


async def test_lists_accessible_projects_except_own_and_archived(client, db):
    _me, task = await _world(client, db)
    section = await _section(db, task)
    assert section.startswith(HEADING)
    assert "- ANS — Answers: " in section
    for key in ("ASK", "OLD", "HID"):
        assert f"- {key} — " not in section
    assert "Ask only the projects listed here." in section
    assert "ask_project(project_key, question, context)" in section


async def test_escapes_project_name_and_description(client, db):
    _me, task = await _world(client, db)
    line = _line(await _section(db, task), "ANS")
    assert "<b>" not in line and "\n" not in line
    assert len(line.split(": ", 1)[1]) <= 151  # the description, cut at about 150 characters


async def test_marks_and_orders_mentioned_projects(client, db):
    me, task = await _world(client, db, description="Match how ANS signs in")
    await make_project(client, db, "AAA", me)
    await login(client, me)
    section = await _section(db, task)
    lines = [ln for ln in section.splitlines() if ln.startswith("- ") and " — " in ln]
    assert lines[0].startswith("- ANS — ") and lines[0].endswith("← mentioned in this task")
    assert "mentioned" not in _line(section, "AAA")


async def test_lowercase_word_does_not_mark_key():
    projects = [SimpleNamespace(key="API", name="Gateway"), SimpleNamespace(key="WEB", name="Customer web app")]
    assert a2a_ctx.mentioned_keys(projects, ["call the api from the web"]) == set()
    assert a2a_ctx.mentioned_keys(projects, ["call API"]) == {"API"}
    assert a2a_ctx.mentioned_keys(projects, ["like the CUSTOMER WEB APP does"]) == {"WEB"}
    assert a2a_ctx.mentioned_keys(projects, ["RAPID builds"]) == set()


async def test_chat_messages_count_as_mentions(client, db):
    me, task = await _world(client, db, description="")
    chat = Chat(project_id=task.project_id, started_by=me.id, title="Chat")
    db.add(chat)
    await db.flush()
    task.chat_id, task.chat_round, task.in_chat = chat.id, 1, True
    db.add(Comment(task_id=task.id, author_user_id=me.id, body_md="do it like ANS", to_agent_name="agent"))
    await db.commit()
    assert "← mentioned in this chat" not in await _section(db, task)  # not a message to the agent
    await db.execute(update(Comment).where(Comment.task_id == task.id).values(to_agent_id=await _an_agent(db, me)))
    await db.commit()
    assert _line(await _section(db, task), "ANS").endswith("← mentioned in this chat")


async def _an_agent(db, owner) -> uuid.UUID:
    from app.agents.models import Agent

    agent = Agent(owner_id=owner.id, name=f"a-{uuid.uuid4().hex[:4]}", program="claude_code")
    db.add(agent)
    await db.flush()
    return agent.id


async def test_absent_for_finish_and_without_other_projects(client, db):
    _me, task = await _world(client, db)
    assert await _section(db, task, RunRole.finish) is None
    lonely = await make_user(db)
    await make_project(client, db, "SOLO", lonely)
    await login(client, lonely)
    r = await client.post("/api/projects/SOLO/tasks", json={"title": "Alone"})
    solo = await db.get(Task, uuid.UUID(r.json()["id"]))
    solo.assignee_user_id = lonely.id
    await db.commit()
    assert await _section(db, solo) is None


async def test_left_line_counts_and_runs_out(client, db):
    _me, task = await _world(client, db)
    assert "You can ask up to 20 questions for this task; 20 are left." in await _section(db, task)
    ans = await db.scalar(select(Project.id).where(Project.key == "ANS"))
    for n in range(1, 4):
        db.add(Question(target_project_id=ans, number=n, from_task_id=task.id, title="t", body="t"))
    await db.commit()
    assert "20 questions for this task; 17 are left." in await _section(db, task)
    for n in range(4, 21):
        db.add(Question(target_project_id=ans, number=n, from_task_id=task.id, title="t", body="t",
                        status=QuestionStatus.withdrawn))
    await db.commit()
    assert ("You've used all 20 questions for this task: carry on with what you have, or ask the person."
            in await _section(db, task))


async def _answered(db, task, number=1, text="Signed with HMAC") -> Question:
    ans = await db.scalar(select(Project.id).where(Project.key == "ANS"))
    q = Question(target_project_id=ans, number=number, from_task_id=task.id, title="How signed?", body="b",
                 status=QuestionStatus.answered, answer_md=text,
                 citations=[{"path": "app/sign.py", "start_line": 1, "end_line": 3}])
    db.add(q)
    await db.commit()
    return q


async def test_resume_tail_carries_undelivered_answers_once(client, db):
    _me, task = await _world(client, db)
    q = await _answered(db, task)
    tail = await a2a_ctx.resume_tail(db, task, RunRole.implement)
    assert "ANS-Q1" in tail and "Signed with HMAC" in tail and '<untrusted source="answer">' in tail
    assert "You can ask other projects with ask_project" in tail and "are left." in tail
    await db.refresh(q)
    assert q.delivered_at is not None
    again = await a2a_ctx.resume_tail(db, task, RunRole.implement)
    assert "Signed with HMAC" not in again and "You can ask other projects with ask_project" in again


async def test_fresh_prompt_answers_stamp_delivered(client, db):
    _me, task = await _world(client, db)
    q = await _answered(db, task)
    section = await a2a_ctx.a2a_context(db, task, RunRole.implement)
    assert "Signed with HMAC" in section
    await db.refresh(q)
    assert q.delivered_at is not None


async def test_providers_registered():
    from app.workflow import context

    a2a_ctx.register()
    assert a2a_ctx.projects_context in context.context_providers
    assert a2a_ctx.resume_tail in context.resume_providers
