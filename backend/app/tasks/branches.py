"""Branch from: the branch a task's work starts from (git's own branch-name rules), and when it may change."""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.models import Task

MAX_BRANCH_NAME = 200
_FORBIDDEN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//")


def valid_branch_name(name: str) -> bool:
    """`git check-ref-format --branch` rules, without asking git."""
    if not name or len(name) > MAX_BRANCH_NAME or name == "@" or _FORBIDDEN.search(name):
        return False
    if name.startswith(("-", "/")) or name.endswith(("/", ".", ".lock")):
        return False
    return not any(part.startswith(".") or part.endswith(".lock") for part in name.split("/"))


async def branch_from_locked(db: AsyncSession, task: Task) -> bool:
    """Locked once the task's branch exists (its start branch is recorded), or once a connect-only workflow has
    started: changing it then would point the work and its delivery at different branches."""
    if task.start_branch is not None:
        return True
    from app.workflow.models import Driver, TaskWorkflow, WorkflowStatus  # local: the workflow imports tasks

    wf = await db.get(TaskWorkflow, task.id)
    return wf is not None and wf.driver == Driver.connect_only and wf.status != WorkflowStatus.idle
