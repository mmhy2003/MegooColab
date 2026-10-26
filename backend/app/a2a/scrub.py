"""Removes likely secrets from answers before they are stored (A2A-7). Defence in depth: the answering
session is told never to reveal secrets, and this catches the common shapes if it does anyway."""

import re

REDACTED = "[redacted]"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), REDACTED),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bmg[cr]_[A-Za-z0-9_-]{20,}"), REDACTED),
    # key = value: keep the name, drop the value
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"),
     r"\1\2" + REDACTED),
]


def scrub(text: str) -> tuple[str, bool]:
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out, out != text
