"""Follow-up tasks a design proposes (MC-81): what the agent submits and what the person approves."""

import pytest
from fastapi import HTTPException

from app.workflow.follow_ups import clean_proposed, clean_reviewed


def _code(fn, items) -> str:
    with pytest.raises(HTTPException) as e:
        fn(items)
    assert e.value.status_code == 422
    return e.value.detail


def test_clean_proposed():
    assert clean_proposed(None) == []
    assert clean_proposed([]) == []
    assert clean_proposed([
        {"title": "  Phase 2\x00 ", "type": "story", "description_md": "Do\x00 the rest "},
        {"title": "Phase 3"},
    ]) == [
        {"title": "Phase 2", "type": "story", "description_md": "Do the rest ", "task_id": None},
        {"title": "Phase 3", "type": "task", "description_md": "", "task_id": None},
    ]


def test_clean_proposed_refuses():
    ok = {"title": "t", "type": "task", "description_md": ""}
    for bad in (
        {"title": "t"},
        [ok] * 11,
        ["t"],
        [{**ok, "title": "  "}],
        [{**ok, "type": "epic"}],
        [{**ok, "type": "subtask"}],
        [{**ok, "description_md": 3}],
    ):
        assert _code(clean_proposed, bad) == "invalid_follow_ups"
    assert _code(clean_proposed, [{**ok, "title": "t" * 501}]) == "too_large"
    assert _code(clean_proposed, [{**ok, "description_md": "d" * 4001}]) == "too_large"
    assert len(clean_proposed([ok] * 10)) == 10


def test_clean_reviewed():
    ok = {"title": "t", "type": "bug", "description_md": "d", "create": True}
    assert _code(clean_reviewed, [{"title": "t"}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, [{**ok, "create": "yes"}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, [{**ok, "title": " "}]) == "invalid_follow_ups"
    assert _code(clean_reviewed, None) == "invalid_follow_ups"
    assert clean_reviewed([
        {**ok, "title": "B"},
        {**ok, "title": " ", "create": False},
        {**ok, "title": "A", "create": False},
    ]) == [
        {"title": "B", "type": "bug", "description_md": "d", "task_id": None, "create": True},
        {"title": "A", "type": "bug", "description_md": "d", "task_id": None, "create": False},
    ]
