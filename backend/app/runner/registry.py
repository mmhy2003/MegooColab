"""In-process registry of live runner connections: one per runner token, that is one per machine.

Single backend worker, event loop only: no locks, no threads.
"""

import asyncio
import contextlib
import json
import time
import uuid

from fastapi import WebSocket

from app.runner.protocol import CLOSE_REPLACED, ServerMessage

WORKFLOW_CAPABILITY = "workflow/1"
WORKFLOW_PROBLEM = "runner too old for workflows — update megoocolab-runner"
# the runner starts task branches from run_start.branch and reports where it started (Branch from)
BRANCH_CAPABILITY = "branch/1"
BRANCH_PROBLEM = "runner too old to choose the start branch — update megoocolab-runner"


class RunnerClosed(Exception):
    """The connection is closed (or the peer is gone): the message was not delivered."""


class RunnerConn:
    def __init__(self, token_id: uuid.UUID, user_id: uuid.UUID, socket: WebSocket) -> None:
        self.token_id = token_id  # the runner token it signed in with: its machine
        self.user_id = user_id
        self.socket = socket
        self.last_seen = time.monotonic()
        self.problems: dict[uuid.UUID, list[str]] = {}
        self._available: set[uuid.UUID] = set()
        self.owned_agents: set[uuid.UUID] = set()  # the agents linked to its token, as of the last welcome
        self.last_welcome: dict | None = None
        self.close_code: int | None = None  # why the server closed it, if it did
        self.closed = asyncio.Event()  # set once the server has closed this connection
        self.capabilities: set[str] = set()  # from the runner's hello; empty for a v1 runner
        self.version: str | None = None  # from the hello: megoocolab-runner's version and operating system
        self.os: str | None = None
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
        self.close_code = code
        self.closed.set()
        with contextlib.suppress(Exception):  # the peer may already be gone
            await self.socket.close(code=code)


class RunnerRegistry:
    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, RunnerConn] = {}  # by token id

    async def connect(self, token_id: uuid.UUID, user_id: uuid.UUID, socket: WebSocket) -> RunnerConn:
        """Register a new connection; an older one on the same token is closed with 4409."""
        conn = RunnerConn(token_id, user_id, socket)
        old = self._conns.get(token_id)
        self._conns[token_id] = conn
        if old is not None:
            await old.close(CLOSE_REPLACED)
        return conn

    def disconnect(self, conn: RunnerConn) -> None:
        # a replaced connection must not unregister its successor
        if self._conns.get(conn.token_id) is conn:
            del self._conns[conn.token_id]

    def _live(self) -> list[RunnerConn]:
        """Connections that are not closed; one closed but not yet unregistered does not count."""
        return [conn for conn in self._conns.values() if not conn.closed.is_set()]

    def conn_for_token(self, token_id: uuid.UUID) -> RunnerConn | None:
        conn = self._conns.get(token_id)
        return conn if conn is not None and not conn.closed.is_set() else None

    def conns_for_user(self, user_id: uuid.UUID) -> list[RunnerConn]:
        return [conn for conn in self._live() if conn.user_id == user_id]

    def conn_for_agent(self, agent_id: uuid.UUID) -> RunnerConn | None:
        """The live connection of the agent's machine (its welcome lists the agent)."""
        return next((conn for conn in self._live() if agent_id in conn.owned_agents), None)

    def conn_for_run(self, run_id: uuid.UUID) -> RunnerConn | None:
        """The live connection the run was sent over."""
        return next((conn for conn in self._live() if run_id in conn.run_ids), None)

    def is_available(self, agent_id: uuid.UUID) -> bool:
        return any(agent_id in conn.available for conn in self._live())

    def agent_supports(self, agent_id: uuid.UUID, capability: str) -> bool:
        conn = self.conn_for_agent(agent_id)
        return conn is not None and capability in conn.capabilities

    def connected_count(self) -> int:
        """Live connections to this backend (closed ones not yet unregistered do not count)."""
        return len(self._live())


registry = RunnerRegistry()
