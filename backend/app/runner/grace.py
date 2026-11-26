"""How long a dropped runner's running runs wait for it to come back (MC-214). One deadline per runner token, in this
process. The server waits MARGIN_SECONDS longer than the runner: each side notices a dead network at its own time."""

from app.core.config import get_settings

MARGIN_SECONDS = 30  # module-level so tests can monkeypatch it


def seconds() -> int:
    """RUNNER_GRACE_SECONDS: how long the runner may hold its runs after a drop; 0 is off."""
    return max(0, get_settings().runner_grace_seconds)
