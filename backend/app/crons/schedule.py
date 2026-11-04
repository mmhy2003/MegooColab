"""Cron schedules: five fields (minute, hour, day of month, month, day of week), checked with plain-English messages,
worded for people, and turned into run times in the cron's time zone. A local time a daylight-saving change skips
doesn't run that day; one that happens twice runs once."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cron_descriptor import Options, get_description
from croniter import croniter
from fastapi import HTTPException, status

MIN_GAP_SECONDS = 5 * 60
CHECKED_OCCURRENCES = 20

FIELDS = [
    ("Minute", 0, 59, {}),
    ("Hour", 0, 23, {}),
    ("Day of month", 1, 31, {}),
    ("Month", 1, 12, {m: i + 1 for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}),
    ("Day of week", 0, 7, {d: i for i, d in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}),
]
PART = re.compile(r"^(\*|[A-Z0-9]+(?:-[A-Z0-9]+)?)(?:/(\d+))?$")


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": code, "message": message})


def _value(token: str, name: str, low: int, high: int, names: dict[str, int]) -> int:
    if token in names:
        return names[token]
    if not token.isdigit():
        raise _refuse("schedule_invalid", f"{name} must be {low}–{high} (you wrote {token})")
    n = int(token)
    if not low <= n <= high:
        raise _refuse("schedule_invalid", f"{name} must be {low}–{high} (you wrote {n})")
    return n


def _check_field(text: str, name: str, low: int, high: int, names: dict[str, int]) -> None:
    for part in text.upper().split(","):
        m = PART.match(part)
        if not m:
            raise _refuse("schedule_invalid", f"{name} is not understood: {part or '(empty)'}")
        base, step = m.group(1), m.group(2)
        if step is not None and int(step) == 0:
            raise _refuse("schedule_invalid", f"{name}: a step of 0 never repeats")
        if base == "*":
            continue
        ends = [_value(t, name, low, high, names) for t in base.split("-")]
        if len(ends) == 2 and ends[0] > ends[1]:
            raise _refuse("schedule_invalid", f"{name}: a range must go from low to high ({base})")


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise _refuse("timezone_invalid", f"Unknown time zone: {tz}") from None


def check(expr: str, tz: str) -> None:
    """422 {code, message} for anything but a valid five-field expression in a known zone, at most every 5 minutes."""
    fields = expr.split()
    if len(fields) != 5:
        raise _refuse("schedule_invalid", "Use five fields: minute, hour, day of month, month, day of week")
    for text, (name, low, high, names) in zip(fields, FIELDS):
        _check_field(text, name, low, high, names)
    _zone(tz)
    if not croniter.is_valid(expr):
        raise _refuse("schedule_invalid", "This schedule is not understood")
    times = next_times(expr, tz, datetime.now(UTC), CHECKED_OCCURRENCES)
    if any((b - a).total_seconds() < MIN_GAP_SECONDS for a, b in zip(times, times[1:])):
        raise _refuse("schedule_too_frequent", "A cron can run at most every 5 minutes")


def describe(expr: str) -> str:
    options = Options()
    options.use_24hour_time_format = True
    return get_description(expr, options)


def next_times(expr: str, tz: str, after: datetime, n: int) -> list[datetime]:
    """The next `n` run times after `after`, in UTC. The schedule is read in the zone's wall-clock time: a time that
    doesn't exist on a daylight-saving day is skipped, one that happens twice is taken once (its first)."""
    zone = _zone(tz)
    wall = after.astimezone(zone).replace(tzinfo=None)
    it = croniter(expr, wall)
    out: list[datetime] = []
    while len(out) < n:
        local = it.get_next(datetime)
        aware = local.replace(tzinfo=zone, fold=0)
        if aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local:
            continue  # skipped by a daylight-saving change
        out.append(aware.astimezone(UTC))
    return out
