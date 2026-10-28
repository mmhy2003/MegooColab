"""A small world for dashboard tests: PAY (the viewer's project), WEB (one the viewer cannot open), and helpers that
insert rows directly, so each test states exactly the tasks, workflows, runs and questions it counts."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.a2a.models import Question
from app.agent_runs.models import AgentRun
from app.agents.models import Agent, AgentBinding
from app.auth.models import Role, User
from app.projects.models import BoardColumn, Project
from app.tasks.models import Task
from app.teams.models import Team
from app.workflow.models import TaskWorkflow
from tests.factories import make_project, make_user


@dataclass
class World:
    viewer: User
    other: User
    admin: User
    pay: Project
    web: Project
    pay_team: Team
    pay_manager: User
    agent: Agent
    other_agent: Agent


async def _agent(db, owner: User, name: str, project: Project) -> Agent:
    agent = Agent(owner_id=owner.id, name=name, program="claude_code")
    db.add(agent)
    await db.flush()
    db.add(AgentBinding(agent_id=agent.id, project_id=project.id, local_path=f"/work/{project.key.lower()}"))
    await db.commit()
    return agent


@pytest.fixture
async def world(client, db) -> World:
    viewer = await make_user(db, name="Vera Viewer")
    other = await make_user(db, name="Otto Other")
    admin = await make_user(db, role=Role.admin, name="Ada Admin")
    pay_json, pay_manager, pay_team = await make_project(client, db, "PAY", viewer)
    web_json, _web_manager, _web_team = await make_project(client, db, "WEB", other)
    pay = await db.get(Project, uuid.UUID(pay_json["id"]))
    web = await db.get(Project, uuid.UUID(web_json["id"]))
    return World(
        viewer=viewer, other=other, admin=admin, pay=pay, web=web, pay_team=pay_team, pay_manager=pay_manager,
        agent=await _agent(db, viewer, "Viewer bot", pay), other_agent=await _agent(db, other, "Other bot", web),
    )


async def column_id(db, project: Project, category: str) -> uuid.UUID:
    return await db.scalar(
        select(BoardColumn.id).where(BoardColumn.project_id == project.id, BoardColumn.category == category)
        .order_by(BoardColumn.position).limit(1)
    )


async def add_task(db, project: Project, *, type: str = "task", category: str = "before", user: User | None = None,
                   agent: Agent | None = None, due: date | None = None, completed_at: datetime | None = None,
                   title: str = "T") -> Task:
    number = await db.scalar(
        update(Project).where(Project.id == project.id).values(next_task_number=Project.next_task_number + 1)
        .returning(Project.next_task_number)
    ) - 1
    task = Task(project_id=project.id, number=number, type=type, title=title,
                column_id=await column_id(db, project, category), position=float(number),
                assignee_user_id=user.id if user else None, assignee_agent_id=agent.id if agent else None,
                due_date=due, completed_at=completed_at)
    db.add(task)
    await db.commit()
    task.key = f"{project.key}-{number}"  # plain attribute, for task_key()
    return task


def task_key(task: Task) -> str:
    return task.key


async def add_workflow(db, task: Task, *, stage: str, status: str, needs: str | None = None, driver: str = "runner",
                       agent: Agent | None = None, waiting_since: datetime | None = None, started: bool = True,
                       finished_at: datetime | None = None) -> TaskWorkflow:
    wf = TaskWorkflow(task_id=task.id, stage=stage, status=status, needs=needs, driver=driver,
                      agent_id=agent.id if agent else None,
                      started_at=datetime.now(UTC) - timedelta(hours=1) if started else None, finished_at=finished_at)
    if status == "waiting_human":
        wf.waiting_since = waiting_since or datetime.now(UTC)
    db.add(wf)
    await db.commit()
    return wf


async def add_run(db, agent: Agent, *, task: Task | None = None, question: Question | None = None,
                  status: str = "running", stage: str | None = None, step: int | None = None,
                  started_at: datetime | None = None, finished_at: datetime | None = None) -> AgentRun:
    run = AgentRun(task_id=task.id if task else None, question_id=question.id if question else None,
                   agent_id=agent.id, requested_by=agent.owner_id, policy="workspace", prompt="", status=status,
                   stage=stage, step=step, started_at=started_at, finished_at=finished_at)
    db.add(run)
    await db.commit()
    return run


async def add_question(db, project: Project, *, status: str, from_task: Task | None = None,
                       draft_agent: Agent | None = None, title: str = "Q") -> Question:
    number = await db.scalar(
        update(Project).where(Project.id == project.id).values(next_question_number=Project.next_question_number + 1)
        .returning(Project.next_question_number)
    ) - 1
    q = Question(target_project_id=project.id, number=number, title=title, body="", status=status,
                 from_task_id=from_task.id if from_task else None,
                 draft_agent_id=draft_agent.id if draft_agent else None, draft_md="draft" if draft_agent else None)
    db.add(q)
    await db.commit()
    return q


async def dash(client, scope: str | None = None) -> dict:
    r = await client.get("/api/dashboard", params={"scope": scope} if scope else None)
    assert r.status_code == 200, r.text
    return r.json()
