from pydantic import BaseModel

from app.workflow.models import Driver, Enforcement, Needs, Stage, WorkflowStatus


class TaskWorkflowOut(BaseModel):
    driver: Driver
    stage: Stage
    status: WorkflowStatus
    needs: Needs | None
    enforcement: Enforcement
    current_step: int | None
    steps_total: int | None
    escalation_reason: str | None
