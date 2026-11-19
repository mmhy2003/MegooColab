"""Runs at work now, described once for every screen that lists them: the Dashboard's Running now and the Agents
pages. A run works on a task (or a chat's round), answers a question, runs a cron or writes a Knowledge Base draft."""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.a2a.models import Question
from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.schemas import RunningItem
from app.agents.models import Agent
from app.chats.models import Chat
from app.chats.service import chat_link
from app.crons.models import Cron, CronRun
from app.dashboard.scope import task_link
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow.models import DocKind, DocStatus, Stage, TaskWorkflow, WorkflowDocument


def run_targets(*columns) -> Select:
    """A select over runs with what each works on joined: its task, its question, or its cron run and cron."""
    return (
        select(*columns).select_from(AgentRun)
        .outerjoin(Task, Task.id == AgentRun.task_id)
        .outerjoin(Question, Question.id == AgentRun.question_id)
        .outerjoin(CronRun, CronRun.id == AgentRun.cron_run_id)
        .outerjoin(Cron, Cron.id == CronRun.cron_id)
    )


def run_project_id() -> ColumnElement[uuid.UUID]:
    """The project a run works in (over run_targets): its task's, its question's target, or its cron's; None for a
    Knowledge Base draft."""
    return func.coalesce(Task.project_id, Question.target_project_id, Cron.project_id)


async def _running(
    db: AsyncSession, where: ColumnElement[bool], openable: Collection[uuid.UUID] | None
) -> list[tuple[uuid.UUID, RunningItem]]:
    """(agent id, item) for each running run matching `where`, newest started first. `openable`: the projects the
    viewer can open (None: all); a run elsewhere keeps its text but loses its link."""
    asking_task, asking_project = aliased(Task), aliased(Project)
    project_id = run_project_id()
    steps_total = (
        select(func.jsonb_array_length(WorkflowDocument.steps))
        .where(WorkflowDocument.task_id == AgentRun.task_id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc()).limit(1).scalar_subquery()
    )
    stmt = (
        run_targets(AgentRun.agent_id, AgentRun.id, Agent.name, AgentRun.started_at, project_id, Project.key,
                    Task.number, Task.title, Task.chat_id, Task.in_chat, Chat.title, AgentRun.stage, AgentRun.step,
                    steps_total, TaskWorkflow.review_round, AgentRun.question_id, Question.number,
                    asking_project.key, Cron.id, Cron.name)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .outerjoin(Project, Project.id == project_id)
        .outerjoin(Chat, Chat.id == Task.chat_id)
        .outerjoin(TaskWorkflow, TaskWorkflow.task_id == AgentRun.task_id)
        .outerjoin(asking_task, asking_task.id == Question.from_task_id)
        .outerjoin(asking_project, asking_project.id == asking_task.project_id)
        .where(AgentRun.status == RunStatus.running, where)
        .order_by(AgentRun.started_at.desc().nulls_last(), AgentRun.id)
    )
    out = []
    for (agent_id, run_id, name, started, pid, key, number, task_title, chat_id, in_chat, chat_title, stage, step,
         total, rounds, question_id, question_number, asked_from, cron_id, cron_name) in (await db.execute(stmt)).all():
        title = question_key = link = None
        if number is not None and in_chat and chat_id:  # a chat's round; added to the board it is a plain task
            kind, title, link = "chat", chat_title, chat_link(chat_id)
        elif number is not None:
            kind, title, link = "task", task_title, task_link(key, number)
        elif question_id is not None:
            kind, question_key, link = "question", f"{key}-Q{question_number}", f"/questions/{question_id}"
        elif cron_id is not None:
            kind, title, link = "cron", cron_name, f"/projects/{key}/crons/{cron_id}"
        else:
            kind = "draft"  # only the draft's person can open it
        if openable is not None and pid not in openable:
            link = None
        out.append((agent_id, RunningItem(
            run_id=run_id, agent_name=name, started_at=started, kind=kind, title=title,
            task_key=f"{key}-{number}" if number is not None else None, question_key=question_key,
            stage=stage, step=step if stage == Stage.build else None,
            steps_total=total if stage == Stage.build else None,
            review_round=rounds if stage == Stage.review else None,
            question_from=asked_from if question_id else None,
            link=link, chat_id=chat_id if kind == "chat" else None,
        )))
    return out


async def running_items(db: AsyncSession, where: ColumnElement[bool]) -> list[RunningItem]:
    """The running runs matching `where` (a condition over run_targets), newest started first."""
    return [item for _, item in await _running(db, where, None)]


async def running_by_agent(
    db: AsyncSession, agent_ids: Collection[uuid.UUID], openable: Collection[uuid.UUID] | None
) -> dict[uuid.UUID, list[RunningItem]]:
    """Each agent's running runs, drafts and cron runs too, newest started first; agents with none are left out."""
    by_agent: dict[uuid.UUID, list[RunningItem]] = {}
    if agent_ids:
        for agent_id, item in await _running(db, AgentRun.agent_id.in_(set(agent_ids)), openable):
            by_agent.setdefault(agent_id, []).append(item)
    return by_agent
