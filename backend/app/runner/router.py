import asyncio
import contextlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app.agent_runs.service import (
    apply_update,
    dispatch_pending,
    fail_disconnected_runs,
    fail_unclaimed_runs,
    finish_run,
)
from app.agents.models import Agent, AgentBinding
from app.agents.service import bound_project_ids, publish_agents_updated
from app.auth.models import TokenScope
from app.auth.tokens import resolve_bearer
from app.core.db import SessionLocal
from app.core.events import Event, hub
from app.projects.models import Project
from app.runner.protocol import (
    CLOSE_IDLE,
    CLOSE_PROTOCOL_ERROR,
    CLOSE_UNAUTHORIZED,
    AgentReport,
    AgentStatus,
    ConfigChanged,
    Hello,
    RunFinished,
    RunUpdate,
    Welcome,
    WelcomeAgent,
    WelcomeBinding,
    runner_message,
)
from app.runner.registry import RunnerClosed, RunnerConn, registry

log = logging.getLogger(__name__)
router = APIRouter()

# module-level so tests can monkeypatch them small
REVALIDATE_EVERY_SECONDS = 15
IDLE_TIMEOUT_SECONDS = 45
RECHECK_EVENTS = {"user.deactivated", "sessions.revoked", "tokens.revoked"}


def _bearer(websocket: WebSocket) -> str | None:
    scheme, _, value = websocket.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def _authorize(raw: str | None) -> uuid.UUID | None:
    """User id behind a live runner-scoped token, else None."""
    if raw is None:
        return None
    async with SessionLocal() as db:
        resolved = await resolve_bearer(db, raw, scope=TokenScope.runner)
        await db.commit()  # persists last_used_at
        return resolved[0].id if resolved else None


async def build_welcome(user_id: uuid.UUID) -> Welcome:
    async with SessionLocal() as db:
        agents = (
            (await db.execute(select(Agent).where(Agent.owner_id == user_id).order_by(Agent.created_at, Agent.id)))
            .scalars()
            .all()
        )
        rows = await db.execute(
            select(AgentBinding.agent_id, Project.key, AgentBinding.local_path)
            .join(Project, Project.id == AgentBinding.project_id)
            .where(AgentBinding.agent_id.in_([a.id for a in agents]))
            .order_by(Project.key)
        )
        bindings: dict[uuid.UUID, list[WelcomeBinding]] = {}
        for agent_id, key, path in rows.all():
            bindings.setdefault(agent_id, []).append(WelcomeBinding(project_key=key, local_path=path))
        return Welcome(
            user_id=user_id,
            agents=[
                WelcomeAgent(
                    agent_id=a.id,
                    name=a.name,
                    program=a.program,
                    max_concurrent_runs=a.max_concurrent_runs,
                    bindings=bindings.get(a.id, []),
                )
                for a in agents
            ],
        )


async def _publish_availability(user_id: uuid.UUID, agent_ids: set[uuid.UUID]) -> None:
    """agents.updated for the projects these agents are bound to (and the owner's own views)."""
    if not agent_ids:
        return
    async with SessionLocal() as db:
        projects: set[uuid.UUID] = set()
        for agent_id in agent_ids:
            projects |= await bound_project_ids(db, agent_id)
        await publish_agents_updated(db, user_id, projects)
        await db.commit()


async def _apply_reports(conn: RunnerConn, reports: list[AgentReport | AgentStatus]) -> None:
    """Record availability for the user's own agents only; publish if anything changed."""
    owned = set(conn.owned_agents)
    changed: set[uuid.UUID] = set()
    for r in reports:
        if r.agent_id in owned and conn.set_availability(r.agent_id, r.available, r.problems):
            changed.add(r.agent_id)
    await _publish_availability(conn.user_id, changed)
    await _dispatch(conn.user_id)


async def _dispatch(user_id: uuid.UUID) -> None:
    """Send queued runs to agents that are now available. A failure must not kill the socket."""
    try:
        from app.a2a.routing import route_queued  # local: a2a imports the run service
        from app.workflow import engine

        async with SessionLocal() as db:
            await route_queued(db)  # queued questions may now have an answering agent (A2A-5)
            await engine.dispatch_queued(db)
            await dispatch_pending(db, user_id)
            await db.commit()
    except Exception:
        log.exception("runner: dispatching queued runs failed")


async def _fail_runs(conn: RunnerConn) -> None:
    async with SessionLocal() as db:
        await fail_disconnected_runs(db, conn)
        await db.commit()


async def _fail_unclaimed(conn: RunnerConn) -> None:
    try:
        async with SessionLocal() as db:
            await fail_unclaimed_runs(db, conn)
            await db.commit()
    except Exception:
        log.exception("runner: failing leftover running runs failed")


async def _run_message(handler, *args) -> None:
    """Apply one run update or finish in its own transaction. A failure must not kill the socket."""
    try:
        async with SessionLocal() as db:
            await handler(db, *args)
            await db.commit()
    except Exception:
        log.exception("runner: handling a run message failed")


async def _send_welcome(conn: RunnerConn, *, announce_change: bool) -> None:
    welcome = await build_welcome(conn.user_id)
    payload = welcome.model_dump(mode="json")
    conn.owned_agents = {a.agent_id for a in welcome.agents}
    conn.retain_agents(conn.owned_agents)
    if announce_change:
        if payload == conn.last_welcome:
            return  # nothing the runner cares about changed (e.g. our own availability events)
        await conn.send(ConfigChanged())
    conn.last_welcome = payload
    await conn.send(welcome)


async def _handle(conn: RunnerConn, text: str) -> bool:
    """Process one runner message. False means a protocol error."""
    try:
        msg = runner_message.validate_python(json.loads(text))
    except (ValueError, ValidationError):
        return False
    conn.touch()
    if isinstance(msg, Hello):
        conn.capabilities = set(msg.capabilities)
        await _fail_unclaimed(conn)
        await _apply_reports(conn, msg.agents)
    elif isinstance(msg, AgentStatus):
        await _apply_reports(conn, [msg])
    elif isinstance(msg, RunUpdate):
        await _run_message(apply_update, conn.user_id, msg.run_id, msg.seq, msg.kind, msg.data)
    elif isinstance(msg, RunFinished):
        await _run_message(finish_run, conn.user_id, msg.run_id, msg.outcome, msg.summary, msg.error, msg)
        conn.run_ids.discard(msg.run_id)
    # Heartbeat only refreshes last_seen
    return True


async def _cancel(*tasks: asyncio.Task) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t


@router.websocket("/api/runner/ws")
async def runner_socket(websocket: WebSocket) -> None:
    # subscribe before authorizing so nothing published after the handshake is missed
    queue = hub.subscribe()
    conn: RunnerConn | None = None
    raw = _bearer(websocket)
    try:
        user_id = await _authorize(raw)
        await websocket.accept()
        if user_id is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        conn = await registry.connect(user_id, websocket)
        await _send_welcome(conn, announce_change=False)
        await _serve(conn, queue, raw)
    except (WebSocketDisconnect, RunnerClosed):  # the runner went away
        pass
    finally:
        hub.unsubscribe(queue)
        if conn is not None:
            registry.disconnect(conn)
            # shielded: a cancelled handler (server shutdown) must still fail its runs
            await asyncio.shield(asyncio.ensure_future(_cleanup(conn)))


async def _cleanup(conn: RunnerConn) -> None:
    lost = set(conn.available)
    try:
        await _fail_runs(conn)
    except Exception:  # never let cleanup raise, but do not hide it
        log.exception("runner disconnect: failing running runs failed")
    try:
        await _publish_availability(conn.user_id, lost)
    except Exception:
        log.exception("runner disconnect: publishing availability failed")


async def _serve(conn: RunnerConn, queue: asyncio.Queue[Event], raw: str | None) -> None:
    ws = conn.socket
    recv = asyncio.create_task(ws.receive())
    event = asyncio.create_task(queue.get())
    replaced = asyncio.create_task(conn.closed.wait())
    next_check = time.monotonic() + REVALIDATE_EVERY_SECONDS
    try:
        while True:
            now = time.monotonic()
            timeout = max(0.0, min(next_check - now, conn.last_seen + IDLE_TIMEOUT_SECONDS - now))
            done, _ = await asyncio.wait(
                {recv, event, replaced}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if replaced in done:
                return  # already closed with 4409
            recheck = False
            if recv in done:
                message = recv.result()
                if message["type"] == "websocket.disconnect":
                    return
                text = message.get("text")
                if text is None or not await _handle(conn, text):
                    await conn.close(CLOSE_PROTOCOL_ERROR)
                    return
                recv = asyncio.create_task(ws.receive())
            if event in done:
                ev: Event = event.result()
                event = asyncio.create_task(queue.get())
                if ev.user_id == conn.user_id and ev.project_id is None:
                    if ev.type in RECHECK_EVENTS:
                        recheck = True
                    elif ev.type == "agents.updated":
                        try:
                            await _send_welcome(conn, announce_change=True)
                        except RunnerClosed:
                            return  # the runner is gone; the caller cleans up
            if time.monotonic() - conn.last_seen >= IDLE_TIMEOUT_SECONDS:
                await conn.close(CLOSE_IDLE)
                return
            if recheck or time.monotonic() >= next_check:
                next_check = time.monotonic() + REVALIDATE_EVERY_SECONDS
                if await _authorize(raw) is None:
                    await conn.close(CLOSE_UNAUTHORIZED)
                    return
    finally:
        await _cancel(recv, event, replaced)
