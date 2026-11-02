"""Tool Hub on a person's machines: what is ticked for each, pushes through the runner, and what it reports.

A push sends the machine's whole wanted set, built when it is delivered (so a machine that was offline gets the
library as it is then). Secrets are decrypted only here, into a push sent to a connection of the token's owner.
"""

import base64
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentProgram
from app.auth.models import PersonalAccessToken, TokenScope, User
from app.core.events import Event, publish
from app.hub import rules, service
from app.hub.models import (
    HubInstall,
    HubMachine,
    HubMachineWant,
    HubPrefs,
    HubTool,
    HubToolFile,
)
from app.hub.schemas import (
    HubMachineAgent,
    HubMachineOut,
    HubMachineTool,
    HubProgramState,
)
from app.runner.protocol import (
    McpPayload,
    SkillFile,
    ToolPayload,
    ToolsDrift,
    ToolsPush,
    ToolsReport,
)
from app.runner.registry import OMP_CAPABILITY, RunnerClosed, RunnerConn, registry

TOOLS_CAPABILITY = "tools/1"
# the runner reads a frame of 64 MiB at most; a push stays well below
MAX_PUSH_BYTES = 48 << 20
# reported states that stay what they are until the next report
_STICKY = {"conflict", "failed", "not_supported", "not_available"}
# states a push still has to bring about
_TO_DO = {"will_install", "update_ready", "will_remove", "changed"}


def _now() -> datetime:
    return datetime.now(UTC)


async def my_machines(db: AsyncSession, user: User) -> list[PersonalAccessToken]:
    rows = await db.execute(
        select(PersonalAccessToken)
        .where(
            PersonalAccessToken.user_id == user.id,
            PersonalAccessToken.revoked_at.is_(None),
            PersonalAccessToken.scopes.contains([TokenScope.runner.value]),
        )
        .order_by(PersonalAccessToken.created_at, PersonalAccessToken.id)
    )
    return list(rows.scalars())


async def machine_or_404(db: AsyncSession, user: User, token_id: uuid.UUID) -> PersonalAccessToken:
    token = await db.get(PersonalAccessToken, token_id)
    if (
        token is None or token.user_id != user.id or token.revoked_at is not None
        or TokenScope.runner.value not in token.scopes
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub_not_your_machine")
    return token


async def _agents(db: AsyncSession, token_id: uuid.UUID) -> list[Agent]:
    rows = await db.execute(select(Agent).where(Agent.runner_token_id == token_id).order_by(Agent.program, Agent.name))
    return list(rows.scalars())


async def machine_programs(db: AsyncSession, token_id: uuid.UUID) -> list[str]:
    """The programs of the agents linked to the machine: a push installs into these only. OMP only for a runner
    that can install for it (omp/1); while the machine is offline the push waits, and is built again on delivery."""
    conn = registry.conn_for_token(token_id)
    programs = {a.program for a in await _agents(db, token_id)}
    if conn is not None and OMP_CAPABILITY not in conn.capabilities:
        programs.discard(AgentProgram.omp)
    return sorted(programs)


def secrets_missing(tool: HubTool) -> bool:
    have = service.read_secrets(tool)
    return any(s not in have for s in service.slots_of(tool))


def resolve_mcp(tool: HubTool, os_: str | None) -> McpPayload | None:
    """The MCP ready for that machine: secrets in place of their slots and placeholders, the command for its
    system. None when it has no command for that system."""
    spec = service.spec_of(tool)
    secrets = service.read_secrets(tool)

    def fill(text: str) -> str:
        return rules.PLACEHOLDER_RE.sub(lambda m: secrets.get(m.group(1), ""), text)

    def values(entries) -> dict[str, str]:
        return {e.name: secrets.get(e.name, "") if e.secret else e.value for e in entries}

    if spec.transport == "http":
        return McpPayload(transport="http", url=fill(spec.url or ""), headers=values(spec.headers))
    command = spec.os_commands.get(os_) if os_ else None
    command = command or spec.command
    if command is None:
        return None
    return McpPayload(transport="stdio", command=command.command, args=[fill(a) for a in command.args],
                      env=values(spec.env))


async def _payload(db: AsyncSession, tool: HubTool, os_: str | None) -> ToolPayload | None:
    base = {"tool_id": str(tool.id), "name": tool.name, "kind": tool.kind, "rev": tool.rev,
            "read_only_safe": tool.read_only_safe}
    if tool.kind == "mcp":
        mcp = resolve_mcp(tool, os_)
        return ToolPayload(**base, mcp=mcp) if mcp else None
    files = (await db.execute(select(HubToolFile).where(HubToolFile.tool_id == tool.id))).scalars()
    return ToolPayload(**base, files=[
        SkillFile(path=f.path, content_b64=base64.b64encode(f.content).decode()) for f in sorted(files, key=lambda f: f.path)
    ])


async def _wanted(db: AsyncSession, token_id: uuid.UUID) -> list[HubTool]:
    rows = await db.execute(
        select(HubTool).join(HubMachineWant, HubMachineWant.tool_id == HubTool.id)
        .where(HubMachineWant.token_id == token_id).order_by(HubTool.name)
    )
    return list(rows.scalars())


async def build_push(db: AsyncSession, token: PersonalAccessToken, machine: HubMachine) -> ToolsPush:
    """The machine's wanted set as it is now. Tools that are removed or have no command for the machine's
    system are left out, so the runner removes them if it installed them before; a tool missing a key is kept as
    it is installed (keep) until the key is set."""
    tools, keep = [], []
    for tool in await _wanted(db, token.id):
        if tool.removed_at is not None:
            continue
        if secrets_missing(tool):
            keep.append(tool.name)
            continue
        payload = await _payload(db, tool, token.runner_os)
        if payload is not None:
            tools.append(payload)
    return ToolsPush(push_id=str(uuid.uuid4()), programs=await machine_programs(db, token.id), tools=tools,
                     take_over=list(machine.take_over), keep=keep)


def _conn(token: PersonalAccessToken) -> RunnerConn | None:
    conn = registry.conn_for_token(token.id)
    return conn if conn is not None and conn.user_id == token.user_id else None


async def deliver(db: AsyncSession, token: PersonalAccessToken) -> bool:
    """Sends a waiting push when the machine's runner is online and takes tools. It stays pending until the runner
    reports, so a push lost with the connection is sent again when it comes back."""
    machine = await db.get(HubMachine, token.id)
    conn = _conn(token)
    if machine is None or not machine.pending or conn is None or TOOLS_CAPABILITY not in conn.capabilities:
        return False
    try:
        await conn.send(await build_push(db, token, machine))
    except RunnerClosed:
        return False
    machine.delivered_at = _now()
    await db.flush()
    return True


async def push(db: AsyncSession, user: User, token: PersonalAccessToken, tool_ids: list[uuid.UUID],
               take_over: list[uuid.UUID]) -> None:
    ids = set(tool_ids)
    tools = list((await db.execute(select(HubTool).where(HubTool.id.in_(ids), HubTool.owner_id == user.id))).scalars())
    if len(tools) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if any(t.removed_at is not None for t in tools):
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_removed")
    conn = _conn(token)
    if conn is not None and TOOLS_CAPABILITY not in conn.capabilities:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_runner_too_old")
    await db.execute(delete(HubMachineWant).where(HubMachineWant.token_id == token.id))
    db.add_all(HubMachineWant(token_id=token.id, tool_id=t.id) for t in tools)
    # what a runner said about tools no longer ticked has nothing more to say
    await db.execute(delete(HubInstall).where(
        HubInstall.token_id == token.id, HubInstall.status.in_(_STICKY),
        or_(HubInstall.tool_id.is_(None), HubInstall.tool_id.not_in(ids)) if ids else true(),
    ))
    machine = await db.get(HubMachine, token.id)
    if machine is None:
        machine = HubMachine(token_id=token.id)
        db.add(machine)
    machine.pending, machine.requested_at = True, _now()
    machine.take_over = [t.name for t in tools if t.id in set(take_over)]
    await db.flush()
    if len((await build_push(db, token, machine)).model_dump_json()) > MAX_PUSH_BYTES:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_push_too_large")
    await deliver(db, token)


async def on_agent_linked(db: AsyncSession, user: User, token_id: uuid.UUID | None) -> None:
    """An agent was put on a machine. On a machine that never had a push, with "install my default set" on,
    the default set (tools whose keys are set) is pushed there."""
    if token_id is None or await db.get(HubMachine, token_id) is not None:
        return
    prefs = await db.get(HubPrefs, user.id)
    if prefs is None or not prefs.auto_default:
        return
    tools = (await db.execute(select(HubTool).where(
        HubTool.owner_id == user.id, HubTool.in_default_set.is_(True), HubTool.removed_at.is_(None)))).scalars()
    db.add(HubMachine(token_id=token_id, pending=True, requested_at=_now()))
    db.add_all(HubMachineWant(token_id=token_id, tool_id=t.id) for t in tools if not secrets_missing(t))
    await db.flush()
    token = await db.get(PersonalAccessToken, token_id)
    await deliver(db, token)


async def _owned_tool_id(db: AsyncSession, token: PersonalAccessToken, raw: str | None) -> uuid.UUID | None:
    try:
        tool_id = uuid.UUID(raw) if raw else None
    except ValueError:
        return None
    if tool_id is None:
        return None
    tool = await db.get(HubTool, tool_id)
    return tool_id if tool is not None and tool.owner_id == token.user_id else None


async def apply_report(db: AsyncSession, token: PersonalAccessToken, report: ToolsReport) -> None:
    for r in report.results:
        key = (HubInstall.token_id == token.id, HubInstall.name == r.name, HubInstall.kind == r.kind,
               HubInstall.program == r.program)
        row = (await db.execute(select(HubInstall).where(*key))).scalar_one_or_none()
        if r.status == "removed":
            if row is not None:
                await db.delete(row)
            continue
        tool_id = await _owned_tool_id(db, token, r.tool_id)
        if row is None:
            row = HubInstall(token_id=token.id, name=r.name, kind=r.kind, program=r.program, status=r.status)
            db.add(row)
        row.tool_id, row.rev, row.status, row.detail = tool_id, r.rev, r.status, r.detail
    machine = await db.get(HubMachine, token.id)
    if machine is not None:
        machine.reported_at, machine.pending, machine.take_over = _now(), False, []
    await publish(db, Event(type="hub.machines", user_id=token.user_id))


async def apply_drift(db: AsyncSession, token: PersonalAccessToken, drift: ToolsDrift) -> None:
    """Hand edits: what the runner installed and no longer finds as it wrote it is "changed"; what was changed
    and is back as written is installed again."""
    off = {(d.name, d.kind, d.program) for d in drift.items}
    rows = (await db.execute(select(HubInstall).where(HubInstall.token_id == token.id))).scalars()
    for row in rows:
        drifted = (row.name, row.kind, row.program) in off
        if row.status == "installed" and drifted:
            row.status = "changed"
        elif row.status == "changed" and not drifted:
            row.status = "installed"
    await publish(db, Event(type="hub.machines", user_id=token.user_id))


def _state(tool: HubTool | None, inst: HubInstall | None, ticked: bool, os_: str | None) -> str | None:
    if inst is not None and inst.status == "failed" and (tool is None or tool.removed_at is not None or not ticked):
        return "failed"  # a removal that did not happen
    if tool is None or tool.removed_at is not None:
        if inst is None:
            return None
        return "removed" if tool is not None else ("will_remove" if inst.status not in _STICKY else None)
    if not ticked:
        return "will_remove" if inst is not None and inst.status not in _STICKY else None
    if secrets_missing(tool):
        return "key_missing"
    if tool.kind == "mcp" and resolve_mcp(tool, os_) is None:
        return "not_available"
    if inst is not None:
        if inst.status in _STICKY or inst.status == "changed":
            return inst.status
        if inst.status == "installed":
            return "installed" if inst.rev == tool.rev else "update_ready"
    return "will_install"


async def machine_out(db: AsyncSession, user: User, token: PersonalAccessToken) -> HubMachineOut:
    machine = await db.get(HubMachine, token.id)
    agents = await _agents(db, token.id)
    programs = sorted({a.program for a in agents})
    conn = _conn(token)
    library = list((await db.execute(
        select(HubTool).where(HubTool.owner_id == user.id).order_by(HubTool.name, HubTool.id))).scalars())
    wants = set((await db.execute(
        select(HubMachineWant.tool_id).where(HubMachineWant.token_id == token.id))).scalars())
    installs = list((await db.execute(select(HubInstall).where(HubInstall.token_id == token.id))).scalars())
    by_tool: dict[uuid.UUID, dict[str, HubInstall]] = {}
    orphans: dict[tuple[str, str], dict[str, HubInstall]] = {}
    ids = {t.id for t in library}
    for i in installs:
        if i.tool_id in ids:
            by_tool.setdefault(i.tool_id, {})[i.program] = i
        else:
            orphans.setdefault((i.name, i.kind), {})[i.program] = i
    # a push that could not be delivered yet: the machine is not connected
    waiting = machine is not None and machine.pending and conn is None

    def states(tool: HubTool | None, mine: dict[str, HubInstall], ticked: bool) -> list[HubProgramState]:
        out = []
        for program in sorted(set(programs) | set(mine)):
            inst = mine.get(program)
            state = _state(tool, inst, ticked, token.runner_os)
            if waiting and state in _TO_DO:
                state = "waiting"
            out.append(HubProgramState(program=program, state=state,
                                    detail=inst.detail if inst is not None and state == "failed" else ""))
        return out

    rows = []
    for tool in library:
        mine = by_tool.get(tool.id, {})
        if tool.removed_at is not None and not mine:
            continue
        rows.append(HubMachineTool(tool_id=tool.id, name=tool.name, kind=tool.kind, ticked=tool.id in wants,
                                programs=states(tool, mine, tool.id in wants)))
    for (name, kind), mine in sorted(orphans.items()):
        rows.append(HubMachineTool(tool_id=None, name=name, kind=kind, ticked=False, programs=states(None, mine, False)))
    out_of_step = bool(machine and machine.pending) or any(p.state not in (None, "installed") for r in rows for p in r.programs)
    return HubMachineOut(
        token_id=token.id,
        name=token.name,
        os=token.runner_os,
        online=conn is not None,
        supports_tools=conn is not None and TOOLS_CAPABILITY in conn.capabilities,
        agents=[HubMachineAgent(id=a.id, name=a.name, program=a.program) for a in agents],
        pending=bool(machine and machine.pending),
        reported_at=machine.reported_at if machine else None,
        tools=rows,
        out_of_step=out_of_step,
    )
