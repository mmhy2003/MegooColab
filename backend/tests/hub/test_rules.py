import io

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.hub.rules import (
    MAX_SKILL_FILE_BYTES,
    NAME_RE,
    flagged_values,
    looks_like_secret,
    normalize_skill_files,
    script_systems,
    secret_slots,
    skill_frontmatter,
)
from app.hub.schemas import Entry, McpSpec


def test_names():
    for ok in ("context7", "ui-review", "a_b"):
        assert NAME_RE.fullmatch(ok)
    for bad in ("Context7", "-x", "a b", "a" * 65):
        assert not NAME_RE.fullmatch(bad)


def test_spec_placeholders():
    spec = McpSpec(transport="http", url="https://x/mcp?key=${API_KEY}", headers=[Entry(name="API_KEY", secret=True)])
    assert secret_slots(spec) == ["API_KEY"]
    with pytest.raises(ValidationError, match="hub_unknown_placeholder"):
        McpSpec(transport="http", url="https://x/mcp?key=${API_KEY}")


def test_spec_shape():
    with pytest.raises(ValidationError):
        McpSpec(transport="http")  # no url
    with pytest.raises(ValidationError):
        McpSpec(transport="http", url="ftp://x")
    with pytest.raises(ValidationError):
        McpSpec(transport="stdio")  # no command at all
    McpSpec(transport="stdio", os_commands={"windows": {"command": "npx.cmd", "args": []}})
    with pytest.raises(ValidationError):
        McpSpec(transport="stdio", command={"command": "x", "args": []}, env=[Entry(name="A"), Entry(name="A")])


def test_looks_like_secret():
    assert looks_like_secret("sk-abcdefgh1234")
    assert looks_like_secret("ghp_" + "a1" * 15)
    for plain in ("npx", "@upstash/context7-mcp", "--api-key", "${API_KEY}", "https://mcp.context7.com/mcp"):
        assert not looks_like_secret(plain)


def test_flagged_values():
    spec = McpSpec(transport="stdio", command={"command": "npx", "args": ["-y", "pkg", "--key", "sk-live1234567890"]})
    assert flagged_values(spec) == ["args[3]"]
    spec = McpSpec(transport="stdio", command={"command": "npx", "args": []}, env=[Entry(name="FOO", value="ghp_" + "b2" * 15)])
    assert flagged_values(spec) == ["env.FOO"]
    spec = McpSpec(transport="http", url="https://x/mcp?token=" + "a1B2" * 8)
    assert flagged_values(spec) == ["url"]
    spec = McpSpec(
        transport="stdio",
        command={"command": "npx", "args": ["-y", "pkg", "--key", "sk-live1234567890"]},
        acknowledged=["args[3]"],
    )
    assert flagged_values(spec) == []
    spec = McpSpec(transport="stdio", command={"command": "npx", "args": []},
                   env=[Entry(name="FOO", value="ghp_" + "b2" * 15, secret=True)])
    assert flagged_values(spec) == []


def test_script_systems():
    assert script_systems("scripts/a.sh") == ["linux", "macos"]
    assert script_systems("run.ps1") == ["windows"]
    assert script_systems("x.py") == ["linux", "macos", "windows"]
    assert script_systems("SKILL.md") is None


def test_frontmatter():
    assert skill_frontmatter("---\nname: ui-review\ndescription: Use when…\n---\n# body") == ("ui-review", "Use when…")
    assert skill_frontmatter("# just a body") == (None, None)


def _code(exc: pytest.ExceptionInfo) -> str:
    assert isinstance(exc.value, HTTPException)
    return exc.value.detail


def test_normalize():
    out = normalize_skill_files([("ui/SKILL.md", b"x"), ("ui/a/b.md", b"y")])
    assert [p for p, _ in out] == ["SKILL.md", "a/b.md"]
    for bad in ("../x", "/x", "C:/x", "a//b"):
        with pytest.raises(HTTPException) as e:
            normalize_skill_files([("SKILL.md", b"x"), (bad, b"y")])
        assert _code(e) == "hub_bad_path"
    with pytest.raises(HTTPException) as e:
        normalize_skill_files([("README.md", b"x")])
    assert _code(e) == "hub_skill_no_skill_md"
    with pytest.raises(HTTPException) as e:
        normalize_skill_files([("SKILL.md", b"x")] + [(f"f{i}.md", b"y") for i in range(100)])
    assert _code(e) == "hub_too_many_files"
    with pytest.raises(HTTPException) as e:
        normalize_skill_files([("SKILL.md", b"x"), ("big.bin", io.BytesIO(b"0" * (MAX_SKILL_FILE_BYTES + 1)).read())])
    assert _code(e) == "hub_skill_too_large"


def test_normalize_backslashes():
    out = normalize_skill_files([("ui\\SKILL.md", b"x"), ("ui\\scripts\\a.sh", b"y")])
    assert [p for p, _ in out] == ["SKILL.md", "scripts/a.sh"]
