"""The panel service (MC-174): what an agent sends with submit_cron_report becomes a validated, read-only A2UI
surface of tiles and charts."""

import copy
import json
import re
from pathlib import Path

import pytest

from app.a2ui import service
from app.a2ui.service import CATALOG_ID, MAX_COMPONENTS, MAX_PANEL_BYTES, FormError, PanelError

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "panels.json").read_text())
VALID = FIXTURES["valid"]
INVALID = FIXTURES["invalid"]
EXAMPLE = next(f["panel"] for f in VALID if f["name"] == "example")


def _with_texts(count: int) -> dict:
    """A Column root with `count` Text children: count + 1 components."""
    return {"components": [{"id": "root", "component": "Column", "children": [f"t{i}" for i in range(count)]},
                           *({"id": f"t{i}", "component": "Text", "text": "."} for i in range(count))]}


def _long_text(size: int) -> dict:
    """A panel of one Text whose JSON is exactly `size` bytes."""
    panel = {"components": [{"id": "root", "component": "Text", "text": ""}]}
    overhead = len(json.dumps(panel, separators=(",", ":")))
    panel["components"][0]["text"] = "x" * (size - overhead)
    return panel


def _bar(i: int) -> dict:
    return {"id": f"c{i}", "component": "Chart", "kind": "bar", "title": f"Chart {i}", "points": {"@path": "/slowest"},
            "x": "suite", "series": [{"key": "seconds", "label": "Time"}]}


@pytest.mark.parametrize("fixture", VALID, ids=[f["name"] for f in VALID])
def test_valid_fixtures_pass(fixture):
    message = service.clean_panel(copy.deepcopy(fixture["panel"]))
    assert message["version"] == "1.0"
    surface = message["createSurface"]
    assert re.fullmatch(r"panel-[0-9a-f]{12}", surface["surfaceId"])
    assert surface["catalogId"] == CATALOG_ID
    assert surface["components"] == fixture["panel"]["components"]
    assert surface["dataModel"] == (fixture["panel"].get("data") or {})


@pytest.mark.parametrize("fixture", INVALID, ids=[f["name"] for f in INVALID])
def test_invalid_fixtures_fail(fixture):
    with pytest.raises(PanelError) as caught:
        service.clean_panel(copy.deepcopy(fixture["panel"]))
    assert caught.value.status_code == 422
    assert caught.value.code == fixture["code"]
    assert caught.value.detail.split("\n")[0] == fixture["code"]
    if "path_contains" in fixture:
        assert any(fixture["path_contains"] in p["path"] for p in caught.value.problems), caught.value.problems
    assert all(p["message"] for p in caught.value.problems)


@pytest.mark.parametrize("panel", [
    None, "x", [], {}, {"components": "root"},
    {"components": EXAMPLE["components"], "data": ["trend"]},
])
def test_a_panel_that_is_not_components_and_data_is_invalid(panel):
    with pytest.raises(PanelError) as caught:
        service.clean_panel(copy.deepcopy(panel))
    assert caught.value.code == "invalid_panel"
    assert caught.value.problems[0]["path"] == "panel"


def test_a_panel_error_is_a_form_error():
    assert issubclass(PanelError, FormError)


def test_too_large_bytes():
    service.clean_panel(_long_text(MAX_PANEL_BYTES))  # exactly 16 KB is allowed
    with pytest.raises(PanelError) as caught:
        service.clean_panel(_long_text(MAX_PANEL_BYTES + 1))
    assert caught.value.code == "too_large"
    assert caught.value.problems[0]["path"] == "panel"


def test_too_many_components():
    service.clean_panel(_with_texts(MAX_COMPONENTS - 1))  # 60 is allowed
    with pytest.raises(PanelError) as caught:
        service.clean_panel(_with_texts(MAX_COMPONENTS))
    assert caught.value.code == "too_large"
    assert caught.value.problems[0]["path"] == "components"


def test_four_charts_pass():
    panel = {"components": [{"id": "root", "component": "Column", "children": [f"c{i}" for i in range(4)]},
                            *(_bar(i) for i in range(4))],
             "data": {"slowest": [{"suite": "api", "seconds": 131}, {"suite": "web", "seconds": 74}]}}
    assert len(service.clean_panel(panel)["createSurface"]["components"]) == 5


def test_the_missing_number_message_names_the_key():
    panel = {"components": [{"id": "c", "component": "Chart", "kind": "line", "title": "Runs",
                             "points": {"@path": "/trend"}, "x": "day",
                             "series": [{"key": "api", "label": "API"}, {"key": "web", "label": "Web"},
                                        {"key": "runer", "label": "Runner"}]}],
             "data": {"trend": [{"day": "Nov 23", "api": 3, "web": 1, "runner": 2},
                                {"day": "Nov 24", "api": 2, "web": 1, "runner": 1}]}}
    with pytest.raises(PanelError) as caught:
        service.clean_panel(panel)
    assert caught.value.code == "invalid_panel"
    assert 'components.c.series.2.key: no point of /trend has a number under "runer"' in caught.value.detail


def test_unwrap_gives_back_what_the_agent_wrote():
    assert service.unwrap(service.clean_panel(copy.deepcopy(EXAMPLE))) == {"components": EXAMPLE["components"],
                                                                           "data": EXAMPLE["data"]}
    tiles = {"components": [{"id": "root", "component": "StatTile", "label": "Open", "value": "1"}]}
    assert service.unwrap(service.clean_panel(copy.deepcopy(tiles))) == {"components": tiles["components"], "data": {}}


def test_nul_is_stripped():
    panel = copy.deepcopy(EXAMPLE)
    panel["components"][3]["label"] = "Pass\x00ed"
    panel["data"]["slow\x00est"] = panel["data"].pop("slowest")
    surface = service.clean_panel(panel)["createSurface"]
    assert surface["components"][3]["label"] == "Passed"
    assert surface["dataModel"]["slowest"] == EXAMPLE["data"]["slowest"]
