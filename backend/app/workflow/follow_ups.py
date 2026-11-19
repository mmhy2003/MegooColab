"""Follow-up tasks a design proposes for the later phases of a split task (MC-81): checked when the agent submits
the design and when a person approves it, and created on approval. Workflow runs never create tasks themselves."""

from fastapi import HTTPException, status

from app.core.text import strip_nul
from app.tasks.models import TaskType

MAX_FOLLOW_UPS = 10
MAX_TITLE = 500
MAX_DESCRIPTION = 4_000
TYPES = frozenset({TaskType.story.value, TaskType.task.value, TaskType.bug.value})


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _entry(item, *, reviewed: bool) -> dict:
    if not isinstance(item, dict):
        raise _422("invalid_follow_ups")
    title, kind, description = item.get("title", ""), item.get("type", "task"), item.get("description_md", "")
    if not all(isinstance(v, str) for v in (title, kind, description)) or kind not in TYPES:
        raise _422("invalid_follow_ups")
    title, description = strip_nul(title).strip(), strip_nul(description)
    entry = {"title": title, "type": kind, "description_md": description, "task_id": None}
    if reviewed:
        create = item.get("create")
        if not isinstance(create, bool):
            raise _422("invalid_follow_ups")
        entry["create"] = create
    if not title and (not reviewed or entry["create"]):
        raise _422("invalid_follow_ups")
    if len(title) > MAX_TITLE or len(description) > MAX_DESCRIPTION:
        raise _422("too_large")
    return entry


def _list(items) -> list:
    if not isinstance(items, list) or len(items) > MAX_FOLLOW_UPS:
        raise _422("invalid_follow_ups")
    return items


def clean_proposed(items) -> list[dict]:
    """What the agent passed to submit_design. None (left out) proposes none."""
    if items is None:
        return []
    return [_entry(i, reviewed=False) for i in _list(items)]


def clean_reviewed(items) -> list[dict]:
    """What the person sent with the approval: the whole list in order, each with `create`. An unticked row the
    person left without a title is dropped."""
    entries = [_entry(i, reviewed=True) for i in _list(items)]
    return [e for e in entries if e["title"]]
