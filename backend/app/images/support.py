"""Whether an agent (or a task's agent) can be sent images: its runner says `images/1` in its hello. An offline
machine counts by its last hello, which is remembered on its token; a connect-only workflow's agent reads them
over MCP, so it can always be sent them."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import PersonalAccessToken
from app.runner.registry import IMAGES_CAPABILITY, registry
from app.tasks.models import Task
from app.workflow.models import Driver, TaskWorkflow


async def agent_takes_images(db: AsyncSession, agent: Agent | None) -> bool:
    if agent is None:
        return False
    conn = registry.conn_for_agent(agent.id)
    if conn is not None:
        return IMAGES_CAPABILITY in conn.capabilities
    if agent.runner_token_id is None:
        return False
    caps = await db.scalar(select(PersonalAccessToken.runner_capabilities).where(PersonalAccessToken.id == agent.runner_token_id))
    return IMAGES_CAPABILITY in (caps or [])


async def task_takes_images(db: AsyncSession, task: Task) -> bool:
    wf = await db.scalar(select(TaskWorkflow).where(TaskWorkflow.task_id == task.id))
    if wf is not None and wf.driver == Driver.connect_only:
        return True
    agent_id: uuid.UUID | None = task.assignee_agent_id or (wf.agent_id if wf is not None else None)
    return await agent_takes_images(db, await db.get(Agent, agent_id) if agent_id else None)
