"""Importing what a machine already has: the runner's scan, kept encrypted, offered back masked, and turned
into library tools for the items the owner picks."""

import base64
import json
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PersonalAccessToken, User
from app.core.crypto import decrypt, encrypt
from app.hub import rules, service
from app.hub.models import HubScan, HubTool
from app.hub.schemas import (
    AcceptItem,
    Entry,
    ImportEntry,
    ImportItem,
    ImportMcp,
    McpSpec,
    ScanOut,
    ToolFileOut,
    ToolOut,
)
from app.runner.protocol import ToolsFound, ToolsScan
from app.runner.registry import RunnerClosed

SCAN_TTL = timedelta(hours=1)
# names that hold keys even when their value does not look like one
_SECRET_NAME = re.compile(r"auth|token|key|secret|passw|credential|cookie", re.IGNORECASE)


def _bad(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


async def start(db: AsyncSession, user: User, token: PersonalAccessToken) -> uuid.UUID:
    from app.hub.machines import TOOLS_CAPABILITY, _conn

    conn = _conn(token)
    if conn is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_runner_offline")
    if TOOLS_CAPABILITY not in conn.capabilities:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_runner_too_old")
    scan = HubScan(token_id=token.id, user_id=user.id, status="waiting")
    db.add(scan)
    await db.flush()
    try:
        await conn.send(ToolsScan(scan_id=str(scan.id)))
    except RunnerClosed:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_runner_offline")
    return scan.id


async def apply_found(db: AsyncSession, token: PersonalAccessToken, found: ToolsFound) -> None:
    """The runner's answer, kept only for the scan it answers, on its own machine."""
    try:
        scan = await db.get(HubScan, uuid.UUID(found.scan_id))
    except ValueError:
        return
    if scan is None or scan.token_id != token.id or scan.status != "waiting":
        return
    scan.result_enc = encrypt(json.dumps([i.model_dump(mode="json", exclude_none=True) for i in found.items]))
    scan.status = "done"


async def _scan(db: AsyncSession, user: User, scan_id: uuid.UUID) -> HubScan:
    scan = await db.get(HubScan, scan_id)
    if scan is None or scan.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if datetime.now(UTC) - scan.created_at > SCAN_TTL:
        await db.delete(scan)
        await db.commit()  # gone for good, though the answer is an error
        raise HTTPException(status.HTTP_410_GONE, "hub_scan_expired")
    return scan


def _merged(scan: HubScan) -> list[dict]:
    """The found items, one per distinct setup: the same MCP or skill found in several programs is one item."""
    groups: dict[str, dict] = {}
    for item in json.loads(decrypt(scan.result_enc)) if scan.result_enc else []:
        body = {k: v for k, v in item.items() if k != "program"}
        key = json.dumps(body, sort_keys=True)
        group = groups.setdefault(key, body | {"programs": []})
        group["programs"] = sorted({*group["programs"], item["program"]})
    return sorted(groups.values(), key=lambda g: (g["name"], g["kind"], g["programs"]))


def _suggest(name: str, value: str) -> bool:
    return rules.looks_like_secret(value) or bool(_SECRET_NAME.search(name))


def _mask(value: str) -> str:
    return "••••" + (value[-4:] if len(value) > 8 else "")


def _entries(values: dict[str, str]) -> list[ImportEntry]:
    out = []
    for name, value in sorted(values.items()):
        secret = _suggest(name, value)
        out.append(ImportEntry(name=name, value_masked=_mask(value) if secret else value, suggested_secret=secret))
    return out


async def scan_out(db: AsyncSession, user: User, scan_id: uuid.UUID) -> ScanOut:
    scan = await _scan(db, user, scan_id)
    if scan.status != "done":
        return ScanOut(status="waiting", items=[])
    mine = {(t.kind, t.name) for t in (await db.execute(select(HubTool).where(HubTool.owner_id == user.id))).scalars()}
    items = []
    for i, g in enumerate(_merged(scan)):
        mcp = files = None
        if g.get("mcp"):
            m = g["mcp"]
            mcp = ImportMcp(
                transport=m["transport"], url=m.get("url"), command=m.get("command"),
                args=[_mask(a) if rules.looks_like_secret(a) else a for a in m.get("args", [])],
                headers=_entries(m.get("headers", {})), env=_entries(m.get("env", {})),
            )
        if g.get("files") is not None:
            files = [ToolFileOut(path=f["path"], size=len(base64.b64decode(f["content_b64"])),
                                 runs_on=rules.script_systems(f["path"])) for f in g["files"]]
        items.append(ImportItem(index=i, kind=g["kind"], name=g["name"], programs=g["programs"],
                                problem=g.get("problem"), mcp=mcp, files=files,
                                exists_in_library=(g["kind"], g["name"]) in mine))
    return ScanOut(status="done", items=items)


def _spec(m: dict, secret: set[str]) -> tuple[McpSpec, dict[str, str]]:
    headers, env = m.get("headers", {}), m.get("env", {})
    if secret - set(headers) - set(env):
        raise _bad("hub_unknown_secret")
    values = {k: v for k, v in {**headers, **env}.items() if k in secret}
    try:
        if m["transport"] == "http":
            spec = McpSpec(transport="http", url=m.get("url"),
                           headers=[Entry(name=k, value=v, secret=k in secret) for k, v in headers.items()])
        else:
            spec = McpSpec(transport="stdio", command={"command": m.get("command") or "", "args": m.get("args", [])},
                           env=[Entry(name=k, value=v, secret=k in secret) for k, v in env.items()])
    except ValidationError:
        raise _bad("hub_bad_item")
    return spec, values


async def accept(db: AsyncSession, user: User, scan_id: uuid.UUID, picks: list[AcceptItem]) -> list[ToolOut]:
    scan = await _scan(db, user, scan_id)
    merged = _merged(scan)
    tools: list[HubTool] = []
    for pick in picks:
        if pick.index >= len(merged) or merged[pick.index].get("problem"):
            raise _bad("hub_bad_item")
        if not rules.NAME_RE.fullmatch(pick.name):
            raise _bad("hub_bad_name")
        g = merged[pick.index]
        tool = HubTool(owner_id=user.id, kind=g["kind"], name=pick.name, description=pick.description)
        db.add(tool)
        if g["kind"] == "mcp":
            spec, values = _spec(g["mcp"], set(pick.secret))
            service.set_spec(tool, spec)
            service.write_secrets(tool, values)
        try:
            await db.flush()
        except IntegrityError:
            raise HTTPException(status.HTTP_409_CONFLICT, "hub_name_taken")
        if g["kind"] == "skill":
            files = rules.normalize_skill_files(
                [(f["path"], base64.b64decode(f["content_b64"])) for f in g.get("files") or []]
            )
            if not tool.description:
                tool.description = (rules.skill_frontmatter(dict(files)["SKILL.md"].decode("utf-8", "replace"))[1] or "")[:2000]
            await service.replace_files(db, tool, files)
        tools.append(tool)
    await db.delete(scan)
    await db.flush()
    return [await service.tool_out(db, user, t) for t in tools]
