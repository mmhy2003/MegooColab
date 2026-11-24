"""The card service (MC-173): what an agent sends to show_card becomes a validated, read-only A2UI surface."""

import copy
import json
import re
from pathlib import Path

import pytest

from app.a2ui import service
from app.a2ui.service import (
    CARD_COMPONENTS, CATALOG_ID, MAX_CARD_BYTES, MAX_COMPONENTS, MAX_DATA_ITEMS, CardError, FormError,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "cards.json").read_text())
VALID = FIXTURES["valid"]
INVALID = FIXTURES["invalid"]
EXAMPLE = next(f["card"] for f in VALID if f["name"] == "example")
FORM_EXAMPLE = json.loads((Path(__file__).parent / "fixtures" / "forms.json").read_text())["valid"][0]["form"]
CARD_EXAMPLE_FILE = Path(service.__file__).parent / "card_example.json"


def _with_texts(count: int) -> dict:
    """A Column root with `count` Text children: count + 1 components."""
    return {"components": [{"id": "root", "component": "Column", "children": [f"t{i}" for i in range(count)]},
                           *({"id": f"t{i}", "component": "Text", "text": "."} for i in range(count))]}


def _with_rows(count: int) -> dict:
    """A template list over a nested data array of `count` rows."""
    return {"components": [{"id": "root", "component": "List", "children": {"componentId": "row", "path": "/outer/rows"}},
                           {"id": "row", "component": "TaskLink", "task": {"@path": "key"}}],
            "data": {"outer": {"rows": [{"key": f"MC-{i + 1}"} for i in range(count)]}}}


def _long_text(size: int) -> dict:
    """A card of one Text whose JSON is exactly `size` bytes."""
    card = {"components": [{"id": "root", "component": "Text", "text": ""}]}
    overhead = len(json.dumps(card, separators=(",", ":")))
    card["components"][0]["text"] = "x" * (size - overhead)
    return card


@pytest.mark.parametrize("fixture", VALID, ids=[f["name"] for f in VALID])
def test_valid_fixtures_pass(fixture):
    message = service.clean_card(copy.deepcopy(fixture["card"]))
    assert message["version"] == "1.0"
    surface = message["createSurface"]
    assert re.fullmatch(r"card-[0-9a-f]{12}", surface["surfaceId"])
    assert surface["catalogId"] == CATALOG_ID
    assert surface["components"] == fixture["card"]["components"]
    assert surface["dataModel"] == (fixture["card"].get("data") or {})


@pytest.mark.parametrize("fixture", INVALID, ids=[f["name"] for f in INVALID])
def test_invalid_fixtures_fail(fixture):
    with pytest.raises(CardError) as caught:
        service.clean_card(copy.deepcopy(fixture["card"]))
    assert caught.value.status_code == 422
    assert caught.value.code == fixture["code"]
    assert caught.value.detail.split("\n")[0] == fixture["code"]
    if "path_contains" in fixture:
        assert any(fixture["path_contains"] in p["path"] for p in caught.value.problems), caught.value.problems
        assert all(p["message"] for p in caught.value.problems)


@pytest.mark.parametrize("card", [
    None, "a card", [], {}, {"components": "root"}, {"components": ["root"]},
    {"components": EXAMPLE["components"], "data": ["failing"]},
])
def test_a_card_that_is_not_components_and_data_is_invalid(card):
    with pytest.raises(CardError) as caught:
        service.clean_card(copy.deepcopy(card))
    assert caught.value.code == "invalid_card"
    assert caught.value.problems[0]["path"] == "card"


def test_a_card_error_is_a_form_error():
    assert issubclass(CardError, FormError)


def test_too_large_bytes():
    service.clean_card(_long_text(MAX_CARD_BYTES))  # exactly 16 KB is allowed
    with pytest.raises(CardError) as caught:
        service.clean_card(_long_text(MAX_CARD_BYTES + 1))
    assert caught.value.code == "too_large"
    assert caught.value.problems[0]["path"] == "card"


def test_too_many_components():
    service.clean_card(_with_texts(MAX_COMPONENTS - 1))  # 60 is allowed
    with pytest.raises(CardError) as caught:
        service.clean_card(_with_texts(MAX_COMPONENTS))
    assert caught.value.code == "too_large"
    assert caught.value.problems[0]["path"] == "components"


def test_too_many_items_in_a_nested_data_array():
    service.clean_card(_with_rows(MAX_DATA_ITEMS))  # 50 is allowed
    with pytest.raises(CardError) as caught:
        service.clean_card(_with_rows(MAX_DATA_ITEMS + 1))
    assert caught.value.code == "too_large"
    assert caught.value.problems[0]["path"] == "data.outer.rows"


def test_a_bound_task_is_not_checked():
    card = {"components": [{"id": "root", "component": "TaskLink", "task": {"@path": "/key"}}],
            "data": {"key": "not a key"}}
    assert service.clean_card(card)["createSurface"]["dataModel"] == {"key": "not a key"}


def test_nul_is_stripped():
    card = copy.deepcopy(EXAMPLE)
    card["components"][2]["label"] = "Pass\x00ed"
    card["data"]["fail\x00ing"] = card["data"].pop("failing")
    surface = service.clean_card(card)["createSurface"]
    assert surface["components"][2]["label"] == "Passed"
    assert surface["dataModel"]["failing"] == EXAMPLE["data"]["failing"]


def test_card_guide_lists_exactly_the_card_components():
    guide = service.card_guide()
    assert set(guide) == {"instructions_md", "catalog", "example"}
    catalog = guide["catalog"]
    assert catalog["catalogId"] == CATALOG_ID
    assert set(catalog["components"]) == CARD_COMPONENTS
    assert len(catalog["$defs"]["anyComponent"]["oneOf"]) == 9
    for name in catalog["components"]:
        assert f"`{name}`" in guide["instructions_md"]
    assert guide["example"] == json.loads(CARD_EXAMPLE_FILE.read_text())
    service.clean_card(copy.deepcopy(guide["example"]))


@pytest.mark.parametrize("component", [
    {"id": "shown", "component": "Tabs", "tabs": [{"title": "One", "child": "extra"}]},
    {"id": "shown", "component": "List", "children": ["extra"]},
    {"id": "shown", "component": "StatTile", "label": "Open", "value": "1"},
    {"id": "shown", "component": "TaskLink", "task": "MC-181"},
], ids=["Tabs", "List", "StatTile", "TaskLink"])
def test_forms_refuse_the_display_components(component):
    form = copy.deepcopy(FORM_EXAMPLE)
    form["components"][0]["children"] += ["shown"]
    form["components"] += [component, {"id": "extra", "component": "Text", "text": "."}]
    with pytest.raises(FormError) as caught:
        service.clean_form(form)
    assert caught.value.code == "invalid_form"
    assert any(p["path"] == "components.shown.component" for p in caught.value.problems)


CHART = {"id": "shown", "component": "Chart", "kind": "bar", "title": "Slowest suites", "points": {"@path": "/slowest"},
         "x": "suite", "series": [{"key": "seconds", "label": "Time"}], "unit": "s"}


def test_forms_and_cards_refuse_a_chart():
    form = copy.deepcopy(FORM_EXAMPLE)
    form["components"][0]["children"] += ["shown"]
    form["components"] += [copy.deepcopy(CHART)]
    with pytest.raises(FormError) as caught:
        service.clean_form(form)
    assert caught.value.code == "invalid_form"
    assert any(p["path"] == "components.shown.component" for p in caught.value.problems)

    card = {"components": [{**CHART, "id": "root"}], "data": {"slowest": [{"suite": "api", "seconds": 131}]}}
    with pytest.raises(CardError) as caught:
        service.clean_card(card)
    assert caught.value.code == "invalid_card"
    assert any(p["path"] == "components.root.component" for p in caught.value.problems)
