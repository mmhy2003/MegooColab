"""Pure workflow rules with no database or engine dependencies, so any module can import them."""

import uuid

from app.auth.models import Role, User
from app.tasks.models import Task
from app.workflow.models import Driver, TaskWorkflow


def can_act(
    user: User, task: Task, wf: TaskWorkflow | None, manages: bool, agent_owner_id: uuid.UUID | None
) -> bool:
    """WF-6, the pure rule: the owner of the task's agent, a manager of the project (`manages`, admins
    included), or, for connect_only (AGT-32), the human assignee. Read-only viewers never act."""
    if user.role == Role.viewer:
        return False
    if agent_owner_id is not None and agent_owner_id == user.id:
        return True
    if wf is not None and wf.driver == Driver.connect_only and task.assignee_user_id == user.id:
        return True
    return manages
