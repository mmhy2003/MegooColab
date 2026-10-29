"""Log lines carry a timestamp, the level and the logger, with the level in colour on a terminal."""

import asyncio
import io
import logging
import re

import pytest

from app.core import logs

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (?P<level>[A-Z]+) +(?P<name>[\w.]+): (?P<message>.*)$")


def _record(level=logging.INFO, name="app.git.jobs", msg="pushed %s", args=("main",)):
    return logging.LogRecord(name, level, __file__, 1, msg, args, None)


@pytest.fixture
def restore_logging():
    """setup_logging changes process-wide loggers: put them back for the other tests."""
    names = ("", "app", "alembic", *logs.UVICORN_LOGGERS)
    saved = {n: (logging.getLogger(n).handlers[:], logging.getLogger(n).level, logging.getLogger(n).propagate)
             for n in names}
    yield
    for n, (handlers, level, propagate) in saved.items():
        lg = logging.getLogger(n)
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate


def test_a_line_has_the_time_the_level_and_the_logger():
    line = logs.LineFormatter(color=False).format(_record())
    m = LINE.match(line)
    assert m, line
    assert (m["level"], m["name"], m["message"]) == ("INFO", "app.git.jobs", "pushed main")
    assert "\x1b[" not in line


def test_levels_line_up():
    f = logs.LineFormatter(color=False)
    starts = {f.format(_record(level=lv)).index("app.git.jobs") for lv in (logging.INFO, logging.WARNING, logging.ERROR)}
    assert len(starts) == 1


def test_in_colour_the_level_is_coloured_and_the_message_is_not():
    line = logs.LineFormatter(color=True).format(_record(level=logging.ERROR))
    assert "\x1b[31mERROR" in line
    assert line.endswith("\x1b[0m pushed main")
    assert LINE.match(re.sub(r"\x1b\[[0-9;]*m", "", line))


def test_an_exception_follows_its_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    first, *rest = logs.LineFormatter(color=False).format(record).splitlines()
    assert LINE.match(first)
    assert rest[-1] == "ValueError: boom"


class _Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize(("stream", "env", "expected"), [
    (_Tty(), {}, True),
    (io.StringIO(), {}, False),  # a file or docker's log: no escape codes
    (_Tty(), {"NO_COLOR": "1"}, False),
    (io.StringIO(), {"FORCE_COLOR": "1"}, True),
    (_Tty(), {"FORCE_COLOR": "0"}, False),
    (_Tty(), {"NO_COLOR": ""}, True),  # set but empty counts as unset
    (io.StringIO(), {"FORCE_COLOR": ""}, False),
])
def test_colour_on_a_terminal_unless_told_otherwise(stream, env, expected):
    assert logs.wants_color(stream, env) is expected


def test_uvicorn_and_our_loggers_share_one_handler(restore_logging, capsys, monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    access = logging.getLogger("uvicorn.access")
    access.addHandler(logging.StreamHandler(io.StringIO()))  # as uvicorn's own config leaves it
    access.propagate = False
    access.setLevel(logging.INFO)
    logs.setup_logging()
    logs.setup_logging()  # twice (the app is created once per test) still writes each line once
    logging.getLogger("app.git.jobs").info("pushed")
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/api/health", "1.1", 200)
    logging.getLogger("httpx").info("HTTP Request: GET ...")  # libraries speak at warnings and up only
    lines = capsys.readouterr().err.splitlines()
    assert [LINE.match(line)["name"] for line in lines] == ["app.git.jobs", "uvicorn.access"]
    assert lines[1].endswith('127.0.0.1:5000 - "GET /api/health HTTP/1.1" 200')
    assert access.handlers == []


async def test_migrating_on_start_keeps_the_app_log_lines(restore_logging):
    """Alembic's own logging setup is for the alembic command: under the app it would add a second handler."""
    from app.main import run_migrations

    logs.setup_logging()
    before = logging.getLogger().handlers[:]
    await asyncio.to_thread(run_migrations)
    assert logging.getLogger().handlers == before
    assert logging.getLogger().level == logging.WARNING
