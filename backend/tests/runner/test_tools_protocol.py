"""Tool Hub pushes (plan 24): the runner messages, and the machine's system kept from its hello."""

import asyncio
import time

import pytest
from pydantic import ValidationError

from app.auth.models import PersonalAccessToken
from app.core.db import SessionLocal
from app.runner.protocol import (
    ToolsDrift,
    ToolsFound,
    ToolsPush,
    ToolsReport,
    runner_message,
)
from tests.runner.test_runner_ws import URL, _hello, _owner


def test_runner_messages_parse():
    report = runner_message.validate_python({
        "type": "tools_report", "push_id": "p1",
        "results": [{"tool_id": "t1", "name": "ctx", "kind": "mcp", "program": "claude_code", "rev": 3,
                     "status": "installed", "detail": ""}],
    })
    assert isinstance(report, ToolsReport) and report.results[0].status == "installed"
    drift = runner_message.validate_python({
        "type": "tools_drift", "items": [{"name": "ctx", "kind": "mcp", "program": "codex", "status": "changed"}],
    })
    assert isinstance(drift, ToolsDrift)
    found = runner_message.validate_python({
        "type": "tools_found", "scan_id": "s1",
        "items": [{"program": "claude_code", "kind": "mcp", "name": "mine",
                   "mcp": {"transport": "stdio", "headers": {}, "command": "npx", "args": ["-y", "x"], "env": {"K": "v"}}},
                  {"program": "codex", "kind": "skill", "name": "big", "problem": "too large"}],
    })
    assert isinstance(found, ToolsFound) and found.items[0].mcp.command == "npx"


def test_runner_messages_refuse_unknown_fields_and_trim_text():
    with pytest.raises(ValidationError):
        runner_message.validate_python({"type": "tools_drift", "items": [], "extra": 1})
    report = runner_message.validate_python({
        "type": "tools_report", "push_id": "p1",
        "results": [{"name": "ctx", "kind": "mcp", "program": "codex", "status": "failed", "detail": "x\x00" * 400}],
    })
    assert len(report.results[0].detail) == 300 and "\x00" not in report.results[0].detail


def test_push_shape():
    push = ToolsPush(push_id="p1", programs=["claude_code"], tools=[], take_over=[])
    assert push.model_dump()["type"] == "tools_push"


async def test_hello_keeps_the_machine_system(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _, token = await _owner(db, tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        ws.send_json(_hello([]) | {"os": "darwin"})
        ws.receive_json()  # welcome
        deadline = time.monotonic() + 3
        while True:
            async with SessionLocal() as s:
                row = await s.get(PersonalAccessToken, token["id"])
                if row.runner_os == "macos":
                    break
            assert time.monotonic() < deadline, row.runner_os
            await asyncio.sleep(0.02)
