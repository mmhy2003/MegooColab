"""Pure rules of the Tool Hub: names, secrets in an MCP's setup, and a skill's files."""

import re
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.hub.schemas import McpSpec

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

MAX_SKILL_FILES = 100
MAX_SKILL_FILE_BYTES = 1 << 20
MAX_SKILL_BYTES = 2 << 20

_PREFIXED = re.compile(r"(?<![A-Za-z0-9])(?:sk-|sk_|ghp_|gho_|github_pat_|xoxb-|xoxp-|glpat-|AKIA|Bearer )\S{8,}")
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-]{24,}")

_UNIX = ["linux", "macos"]
_ALL = ["linux", "macos", "windows"]
_SCRIPTS = {
    **dict.fromkeys((".sh", ".bash", ".zsh"), _UNIX),
    **dict.fromkeys((".ps1", ".bat", ".cmd"), ["windows"]),
    **dict.fromkeys((".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl"), _ALL),
}


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text)


def secret_slots(spec: "McpSpec") -> list[str]:
    """The names of the secret entries, headers first."""
    return [e.name for e in [*spec.headers, *spec.env] if e.secret]


def looks_like_secret(value: str) -> bool:
    """Whether a value looks like a key or token someone would not want shared."""
    if _PREFIXED.search(value):
        return True
    rest = PLACEHOLDER_RE.sub(" ", value)
    return any(
        re.search(r"\d", m.group()) and re.search(r"[A-Za-z]", m.group()) for m in _TOKEN_RUN.finditer(rest)
    )


def flagged_values(spec: "McpSpec") -> list[str]:
    """Where a value that looks like a secret sits in plain setup (not marked secret, not acknowledged)."""
    found: list[str] = []
    if spec.url and looks_like_secret(spec.url):
        found.append("url")
    if spec.command is not None:
        found += [f"args[{i}]" for i, a in enumerate(spec.command.args) if looks_like_secret(a)]
    for system, c in spec.os_commands.items():
        found += [f"{system}.args[{i}]" for i, a in enumerate(c.args) if looks_like_secret(a)]
    found += [f"headers.{e.name}" for e in spec.headers if not e.secret and looks_like_secret(e.value)]
    found += [f"env.{e.name}" for e in spec.env if not e.secret and looks_like_secret(e.value)]
    return [f for f in found if f not in spec.acknowledged]


def script_systems(path: str) -> list[str] | None:
    """The systems a skill's file runs on when it is a script, else None."""
    name = path.rsplit("/", 1)[-1].lower()
    dot = name.rfind(".")
    return _SCRIPTS.get(name[dot:]) if dot > 0 else None


def skill_frontmatter(text: str) -> tuple[str | None, str | None]:
    """The name and description from a SKILL.md's leading --- block (simple key: value lines)."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found.get("name"), found.get("description")
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            found[key.strip()] = value.strip().strip("\"'")
    return None, None


def _bad(code: str, http: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(http, code)


def normalize_skill_files(entries: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Checks a skill's files and strips one common top folder; raises HTTPException with a hub_* code."""
    parts_list: list[list[str]] = []
    for path, _ in entries:
        p = path.replace("\\", "/")
        if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
            raise _bad("hub_bad_path")
        parts = p.split("/")
        if any(s in ("", ".", "..") for s in parts):
            raise _bad("hub_bad_path")
        parts_list.append(parts)
    if parts_list and all(len(p) > 1 for p in parts_list) and len({p[0] for p in parts_list}) == 1:
        parts_list = [p[1:] for p in parts_list]
    out = [("/".join(parts), data) for parts, (_, data) in zip(parts_list, entries, strict=True)]
    if any(len(p) > 255 for p, _ in out):
        raise _bad("hub_bad_path")
    if len(out) > MAX_SKILL_FILES:
        raise _bad("hub_too_many_files")
    if any(len(d) > MAX_SKILL_FILE_BYTES for _, d in out) or sum(len(d) for _, d in out) > MAX_SKILL_BYTES:
        raise _bad("hub_skill_too_large", status.HTTP_413_CONTENT_TOO_LARGE)
    if "SKILL.md" not in {p for p, _ in out}:
        raise _bad("hub_skill_no_skill_md")
    return out
