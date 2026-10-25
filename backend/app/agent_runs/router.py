import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.agent_runs import service
from app.agent_runs.models import AgentRun
from app.agent_runs.schemas import RunOut
from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.tasks.service import get_task_for

router = APIRouter(tags=["agent-runs"])
# Runs are started only by the workflow engine (app/workflow/engine.py): there is no manual start.


@router.get("/api/tasks/{key}/agent-runs")
async def list_runs(key: str, user: AuthedUser, db: DbSession) -> list[RunOut]:
    task, _ = await get_task_for(db, user, key)
    runs = (
        await db.execute(
            select(AgentRun).where(AgentRun.task_id == task.id).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        )
    ).scalars()
    return await service.runs_out(db, list(runs))


@router.post("/api/agent-runs/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_run(run_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run_not_found")
    await service.cancel_run(db, user, run)
