"""A chat goes round again: the next round starts where the work is, and its agent knows what came before."""

import uuid

from sqlalchemy import update

from app.agent_runs.models import AgentRun, RunStatus
from app.core.db import SessionLocal
from app.git.models import TaskPullRequest
from app.projects.models import Project, ProjectRepository, RepoProvider
from app.tasks.models import Task
from app.workflow import context
from app.workflow.models import DocKind, DocStatus, RunRole, TaskWorkflow, WorkflowDocument, WorkflowStatus
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round


async def _finished(db, task: Task, outcome: str, *, branch="megoo/PAY-1-fix", pr_url=None, pr_state=None) -> None:
    await db.execute(update(AgentRun).where(AgentRun.task_id == task.id).values(status=RunStatus.completed))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task.id).values(
        status=WorkflowStatus.finished, finish_outcome=outcome, branch=branch, pr_url=pr_url, needs=None,
    ))
    if pr_state:
        db.add(TaskPullRequest(task_id=task.id, url=pr_url, state=pr_state))
    await db.commit()


async def _next(client, chat, body="Also add retries to the payment API"):
    return await client.post(f"/api/chats/{chat['id']}/messages", json={"body": body})


async def _repository(db) -> None:
    """The project's code lives in a known repository: its branches can start from one another."""
    project = (await db.execute(Project.__table__.select().where(Project.key == "PAY"))).first()
    db.add(ProjectRepository(project_id=project.id, name="pay", url="https://git.example/pay.git",
                             provider=RepoProvider.github, default_branch="main"))
    await db.commit()


async def test_next_round_branches_from_an_open_pr(client, db):
    await world(client, db)
    await _repository(db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "pr_opened", pr_url="https://git.example/pr/42", pr_state="open")
    r = await _next(client, chat)
    assert r.status_code == 201 and r.json()["intent"] == "new_round"
    rounds = (await client.get(f"/api/chats/{chat['id']}")).json()["rounds"]
    assert [x["n"] for x in rounds] == [1, 2]
    assert rounds[1]["branch_from"] == "megoo/PAY-1-fix" and rounds[1]["stage"] == "brainstorm"
    assert rounds[1]["title"] == "Also add retries to the payment API"


async def test_without_a_repository_the_next_round_starts_from_default(client, db):
    """No repository to start a branch from another branch in: the runner could not do it."""
    await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "pr_opened", pr_url="https://git.example/pr/42", pr_state="open")
    await _next(client, chat)
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["rounds"][1]["branch_from"] is None


async def test_next_round_after_a_merge_starts_from_default(client, db):
    await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "merged_local")
    await _next(client, chat)
    rounds = (await client.get(f"/api/chats/{chat['id']}")).json()["rounds"]
    assert rounds[1]["branch_from"] is None


async def test_next_round_after_a_merged_pr_starts_from_default(client, db):
    await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "pr_opened", pr_url="https://git.example/pr/42", pr_state="merged")
    await _next(client, chat)
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["rounds"][1]["branch_from"] is None


async def test_next_round_needs_the_previous_one_finished(client, db):
    w = await world(client, db)
    chat = await start(client)
    from app.chats import service
    from app.chats.models import Chat

    async with SessionLocal() as s:
        try:
            await service.start_next_round(s, w.owner, await s.get(Chat, uuid.UUID(chat["id"])), "More")
        except Exception as e:  # noqa: BLE001
            assert getattr(e, "detail", None) == "round_not_finished"
        else:
            raise AssertionError("a round was started while the previous one runs")


async def test_round_2_prompt_has_the_earlier_rounds(client, db):
    await world(client, db)
    chat = await start(client)
    r1 = await _round(db, chat)
    db.add(WorkflowDocument(task_id=r1.id, kind=DocKind.plan, version=1, status=DocStatus.approved, body_md="# plan",
                            steps=[{"title": "Validate the email", "detail": "d", "subtask_id": None}]))
    await db.commit()
    await _finished(db, r1, "pr_opened", pr_url="https://git.example/pr/42", pr_state="open")
    await _next(client, chat)
    r2 = await _round(db, chat, 2)
    async with SessionLocal() as s:
        prompt, _ = await context.build_prompt(s, await s.get(Task, r2.id), RunRole.brainstorm)
    section = prompt[prompt.index("## Earlier rounds of this chat"):]
    assert "Round 1" in section and "Fix the empty email crash" in section
    assert "Validate the email" in section and "pull request https://git.example/pr/42" in section
    assert "suggest starting a new chat" in section
