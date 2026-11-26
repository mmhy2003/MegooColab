"""How long a dropped runner's running runs wait for it to come back (MC-214). One deadline per runner token, in this
process. The server waits MARGIN_SECONDS longer than the runner: each side notices a dead network at its own time."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.agent_runs.service import fail_held_runs, running_runs_by_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.runner.registry import RESUME_CAPABILITY, registry

log = logging.getLogger(__name__)
MARGIN_SECONDS = 30  # module-level so tests can monkeypatch it


def seconds() -> int:
    """RUNNER_GRACE_SECONDS: how long the runner may hold its runs after a drop; 0 is off."""
    return max(0, get_settings().runner_grace_seconds)


@dataclass
class _Deadline:
    user_id: uuid.UUID
    run_ids: set[uuid.UUID]
    task: asyncio.Task


_deadlines: dict[uuid.UUID, _Deadline] = {}


def pending(token_id: uuid.UUID) -> bool:
    return token_id in _deadlines


def hold(token_id: uuid.UUID, user_id: uuid.UUID, run_ids: set[uuid.UUID], delay: float | None = None) -> None:
    """Start the token's deadline (grace + margin), or add the runs to the one already running: a connection that
    drops before it sent runs_held does not move the deadline."""
    if (d := _deadlines.get(token_id)) is not None:
        d.run_ids |= run_ids
        return
    delay = seconds() + MARGIN_SECONDS if delay is None else delay
    _deadlines[token_id] = _Deadline(user_id, set(run_ids), asyncio.create_task(_expire_after(token_id, delay)))


def cancel(token_id: uuid.UUID) -> None:
    if (d := _deadlines.pop(token_id, None)) is not None:
        d.task.cancel()


def cancel_all() -> None:
    for token_id in list(_deadlines):
        cancel(token_id)


async def _expire_after(token_id: uuid.UUID, delay: float) -> None:
    await asyncio.sleep(delay)
    d = _deadlines.pop(token_id, None)
    if d is None:
        return
    try:
        await expire(token_id, d.user_id, d.run_ids)
    except Exception:
        log.exception("runner grace: failing the runs of a runner that did not come back failed")


async def expire(token_id: uuid.UUID, user_id: uuid.UUID, run_ids: set[uuid.UUID]) -> None:
    """The deadline passed. A live connection of the token that may still send runs_held (no hello yet, or resume/1
    and not sent) settles it instead; otherwise the runs no live connection holds end as on a disconnect."""
    conn = registry.conn_for_token(token_id)
    if conn is not None and not conn.runs_held_seen and (conn.version is None or RESUME_CAPABILITY in conn.capabilities):
        return
    from app.workflow import engine  # local: the engine imports the run service

    async with SessionLocal() as db:
        await fail_held_runs(db, token_id, user_id, run_ids)
        await db.commit()
        await engine.dispatch_queued(db)


async def hold_at_startup() -> None:
    """Every runner token with running runs gets a deadline: its runner may come back after a restart."""
    if seconds() <= 0:
        return
    async with SessionLocal() as db:
        held = await running_runs_by_token(db)
    for (token_id, user_id), run_ids in held.items():
        hold(token_id, user_id, run_ids)
