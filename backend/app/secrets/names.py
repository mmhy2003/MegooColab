"""What a secret may be called: an environment variable name that never replaces one the runner or an agent program
relies on. The runner checks the same list again (runner/internal/jobs/secrets.go)."""

import re

from fastapi import HTTPException, status

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")

RESERVED = frozenset({
    # the runner's and the agent programs' own environment
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "COMSPEC", "PSMODULEPATH", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "SHELL", "USER", "USERNAME", "LOGNAME", "LANG", "LC_ALL", "PWD", "TERM", "SSH_AUTH_SOCK", "XDG_CONFIG_HOME",
    "XDG_DATA_HOME", "XDG_CACHE_HOME",
    # variables that make a shell or a runtime run code: a project's secret must not run code in members' agents
    "BASH_ENV", "ENV", "PROMPT_COMMAND", "PS4", "IFS", "JAVA_TOOL_OPTIONS",
    # variables that would route or trust traffic elsewhere (the agent's model login, its run token)
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})
RESERVED_PREFIXES = ("MEGOO", "ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_", "OMP_", "GIT_", "LC_", "LD_", "DYLD_",
                     "NODE_", "NPM_CONFIG_", "PYTHON", "PERL5", "RUBY")


def check_name(name: str) -> None:
    if not NAME.fullmatch(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret_name_invalid")
    if name in RESERVED or name.startswith(RESERVED_PREFIXES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret_name_reserved")
