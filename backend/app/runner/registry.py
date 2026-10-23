"""In-process registry of live runner connections (one per user).

Single backend worker, event loop only: no locks, no threads.
"""

import asyncio
import contextlib
import json
import time
import uuid

from fastapi import WebSocket

from app.runner.protocol import CLOSE_REPLACED, ServerMessage


class RunnerClosed(Exception):
    """The connection is closed (or the peer is gone): the message was not delivered."""


class RunnerConn:
    def __init__(self, user_id: uuid.UUID, socket: WebSocket) -> None:
        self.user_id = user_id
        self.socket = socket
        self.last_seen = time.monotonic()
        self.problems: dict[uuid.UUID, list[str]] = {}
        self._available: set[uuid.UUID] = set()
        self.owned_agents: set[uuid.UUID] = set()  # the user's agents, as of the last welcome
        self.last_welcome: dict | None = None
        self.closed = asyncio.Event()  # set once the server has closed this connection
        self.run_ids: set[uuid.UUID] = set()  # runs dispatched over this connection

    @property
    def available(self) -> frozenset[uuid.UUID]:
        return frozenset(self._available)

    def set_availability(self, agent_id: uuid.UUID, available: bool, problems: list[str]) -> bool:
        """Record a report; True if the agent's availability changed."""
        changed = (agent_id in self._available) != available
        if available:
            self._available.add(agent_id)
        else:
            self._available.discard(agent_id)
        self.problems[agent_id] = problems
        return changed

    def retain_agents(self, agent_ids: set[uuid.UUID]) -> None:
        """Forget agents that no longer exist (deleted while connected)."""
        self._available &= agent_ids
        self.problems = {k: v for k, v in self.problems.items() if k in agent_ids}

    def touch(self) -> None:
        self.last_seen = time.monotonic()

    async def send(self, msg: ServerMessage | dict) -> None:
        """Raises RunnerClosed if the message could not be delivered."""
        if self.closed.is_set():
            raise RunnerClosed
        payload = msg if isinstance(msg, dict) else msg.model_dump(mode="json")
        try:
            await self.socket.send_text(json.dumps(payload))
        except Exception as exc:  # starlette raises RuntimeError / WebSocketDisconnect once gone
            raise RunnerClosed from exc

    async def close(self, code: int) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        with contextlib.suppress(Exception):  # the peer may already be gone
            await self.socket.close(code=code)


class RunnerRegistry:
    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, RunnerConn] = {}

    async def connect(self, user_id: uuid.UUID, socket: WebSocket) -> RunnerConn:
        """Register a new connection; an older one for the same user is closed with 4409."""
        conn = RunnerConn(user_id, socket)
        old = self._conns.get(user_id)
        self._conns[user_id] = conn
        if old is not None:
            await old.close(CLOSE_REPLACED)
        return conn

    def disconnect(self, conn: RunnerConn) -> None:
        # a replaced connection must not unregister its successor
        if self._conns.get(conn.user_id) is conn:
            del self._conns[conn.user_id]

    def conn_for_user(self, user_id: uuid.UUID) -> RunnerConn | None:
        """The user's live connection; one that is closed but not yet unregistered does not count."""
        conn = self._conns.get(user_id)
        return conn if conn is not None and not conn.closed.is_set() else None

    def available_agents(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        conn = self.conn_for_user(user_id)
        return set(conn.available) if conn is not None else set()


registry = RunnerRegistry()
