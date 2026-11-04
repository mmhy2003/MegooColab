"""What a secret may be called: an environment variable name that never replaces one the runner or an agent program
relies on. The runner checks the same list again (runner/internal/jobs/secrets.go)."""

import re

from fastapi import HTTPException, status

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")

RESERVED = frozenset({
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "TMPDIR", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "SHELL", "USER", "USERNAME", "LOGNAME",
    "LANG", "LC_ALL", "PWD", "TERM", "SSH_AUTH_SOCK", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
})
RESERVED_PREFIXES = ("MEGOO", "ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_", "OMP_", "GIT_", "LC_")


def check_name(name: str) -> None:
    if not NAME.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret_name_invalid")
    if name in RESERVED or name.startswith(RESERVED_PREFIXES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret_name_reserved")
