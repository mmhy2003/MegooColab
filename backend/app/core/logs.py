"""Log lines for the API and the worker: `2026-10-29 14:03:12.345 INFO     app.git.jobs: message`, the level in
colour on a terminal."""

import logging
import os
import sys
from collections.abc import Mapping
from typing import TextIO

LEVEL_COLORS = {logging.DEBUG: "36", logging.INFO: "32", logging.WARNING: "33", logging.ERROR: "31",
                logging.CRITICAL: "1;31"}
DIM, RESET = "\x1b[2m", "\x1b[0m"
# uvicorn gives these handlers of its own before it imports the app
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
# ours, and the migrations run on start, from INFO; libraries (httpx, mcp, ...) from WARNING only
INFO_LOGGERS = ("app", "alembic")


class LineFormatter(logging.Formatter):
    default_msec_format = "%s.%03d"

    def __init__(self, color: bool) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        self.color = color

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - logging's name
        if not self.color:
            return super().formatMessage(record)
        level = f"\x1b[{LEVEL_COLORS.get(record.levelno, '0')}m{record.levelname:<8}{RESET}"
        return f"{DIM}{record.asctime}{RESET} {level} {DIM}{record.name}:{RESET} {record.message}"


class StderrHandler(logging.StreamHandler):
    """Writes to sys.stderr as it is at each line, like logging's last-resort handler: pytest swaps it."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:  # type: ignore[override]
        return sys.stderr


def wants_color(stream: TextIO, env: Mapping[str, str]) -> bool:
    """A terminal gets colour, a file or docker's log does not; NO_COLOR and FORCE_COLOR (no-color.org) decide first."""
    if env.get("NO_COLOR"):
        return False
    if force := env.get("FORCE_COLOR"):
        return force.lower() not in ("0", "false")
    return stream.isatty()


def _enable_windows_colors() -> None:
    """A Windows console prints escape codes as text until asked to interpret them."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
    mode = ctypes.c_ulong()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


def setup_logging() -> None:
    """Every log line, uvicorn's included, through one handler on the root logger. Safe to call again."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, StderrHandler)]:
        root.removeHandler(handler)
    color = wants_color(sys.stderr, os.environ)
    if color:
        _enable_windows_colors()
    handler = StderrHandler()
    handler.setFormatter(LineFormatter(color))
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    for name in INFO_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
