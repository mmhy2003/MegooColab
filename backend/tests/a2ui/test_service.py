"""The form service: what an agent sends becomes a validated A2UI createSurface message."""

import copy
import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.a2ui import service
from app.a2ui.service import CATALOG_ID, FORM_COMPONENTS, MAX_ANSWER_DATA_BYTES, MAX_FORM_BYTES, FormError
from app.core.text import strip_nul_deep

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "forms.json").read_text())
VALID = FIXTURES["valid"]
INVALID = FIXTURES["invalid"]
EXAMPLE = next(f["form"] for f in VALID if f["name"] == "example")


def _example() -> dict:
    return copy.deepcopy(EXAMPLE)


def _with_checkboxes(count: int) -> dict:
    """The example with `count` more CheckBox inputs under root."""
    form = _example()
    for i in range(count):
        form["components"][0]["children"].append(f"extra{i}")
        form["components"].append({"id": f"extra{i}", "component": "CheckBox", "label": f"Extra {i}",
                                   "value": {"@path": f"/extra{i}"}})
    return form


def _with_texts(count: int) -> dict:
    """The example with `count` more Text components under root."""
    form = _example()
    for i in range(count):
        form["components"][0]["children"].append(f"note{i}")
        form["components"].append({"id": f"note{i}", "component": "Text", "text": "."})
    return form


def _code_of(caught: pytest.ExceptionInfo) -> str:
    return caught.value.detail.split("\n")[0]


@pytest.mark.parametrize("fixture", VALID, ids=[f["name"] for f in VALID])
def test_valid_fixtures_pass(fixture):
    message = service.clean_form(copy.deepcopy(fixture["form"]))
    assert message["version"] == "1.0"
    surface = message["createSurface"]
    assert surface["catalogId"] == CATALOG_ID
    assert re.fullmatch(r"form-[0-9a-f]{12}", surface["surfaceId"])
    assert surface["components"] == fixture["form"]["components"]
    assert surface["dataModel"] == (fixture["form"].get("data") or {})


def test_every_surface_gets_its_own_id():
    first = service.clean_form(_example())["createSurface"]["surfaceId"]
    second = service.clean_form(_example())["createSurface"]["surfaceId"]
    assert first != second


@pytest.mark.parametrize("fixture", INVALID, ids=[f["name"] for f in INVALID])
def test_invalid_fixtures_fail(fixture):
    with pytest.raises(FormError) as caught:
        service.clean_form(copy.deepcopy(fixture["form"]))
    assert caught.value.status_code == 422
    assert caught.value.code == fixture["code"]
    assert _code_of(caught) == fixture["code"]
    if fixture["code"] == "invalid_form":
        assert caught.value.problems
        assert any(fixture["path_contains"] in p["path"] for p in caught.value.problems)
        assert all(p["message"] for p in caught.value.problems)


@pytest.mark.parametrize("form", [
    None, "a form", [], {}, {"components": "root"}, {"components": ["root"]},
    {"components": EXAMPLE["components"], "data": ["name"]},
])
def test_a_form_that_is_not_components_and_data_is_invalid(form):
    with pytest.raises(FormError) as caught:
        service.clean_form(copy.deepcopy(form))
    assert caught.value.code == "invalid_form"
    assert caught.value.problems[0]["path"] == "form"


def test_a_component_name_that_is_not_a_string_is_invalid():
    form = _example()
    form["components"][0]["component"] = ["Column"]
    with pytest.raises(FormError) as caught:
        service.clean_form(form)
    assert caught.value.code == "invalid_form"


def test_at_most_ten_problems():
    form = _example()
    form["components"][0]["children"] += [f"ghost{i}" for i in range(15)]
    with pytest.raises(FormError) as caught:
        service.clean_form(form)
    lines = caught.value.detail.split("\n")
    assert lines[0] == "invalid_form"
    assert 1 <= len(lines[1:]) <= 10
    assert "ghost0" in lines[1]


def test_form_error_keeps_ten_problems():
    error = FormError("invalid_form", [{"path": f"components.c{i}", "message": "bad"} for i in range(15)])
    assert len(error.problems) == 10
    assert error.detail.split("\n") == ["invalid_form", *(f"components.c{i}: bad" for i in range(10))]


def test_too_large_bytes():
    form = _example()
    form["components"][1]["text"] = "x" * MAX_FORM_BYTES
    with pytest.raises(FormError) as caught:
        service.clean_form(form)
    assert caught.value.code == "too_large"


def test_too_many_components():
    service.clean_form(_with_texts(60 - len(EXAMPLE["components"])))  # 60 is allowed
    with pytest.raises(FormError) as caught:
        service.clean_form(_with_texts(61 - len(EXAMPLE["components"])))
    assert caught.value.code == "too_large"


def test_too_many_inputs():
    service.clean_form(_with_checkboxes(20 - 4))  # the example has 4 inputs; 20 is allowed
    with pytest.raises(FormError) as caught:
        service.clean_form(_with_checkboxes(21 - 4))
    assert caught.value.code == "too_large"


def test_nul_is_stripped():
    form = _example()
    form["components"][2]["label"] = "Release\x00 name"
    form["data"]["na\x00me"] = "v\x001"
    message = service.clean_form(form)
    surface = message["createSurface"]
    assert surface["components"][2]["label"] == "Release name"
    assert surface["dataModel"]["name"] == "v1"
    assert "\x00" not in json.dumps(message)


def test_strip_nul_deep():
    value = {"a\x00": ["b\x00", {"c": "d\x00"}, 1, None, True], "n": 2.5}
    assert strip_nul_deep(value) == {"a": ["b", {"c": "d"}, 1, None, True], "n": 2.5}
    assert strip_nul_deep("\x00x") == "x"
    assert strip_nul_deep(7) == 7


def test_field_labels():
    assert service.field_labels(service.clean_form(_example())) == [
        "Release name", "Due date", "Kind", "Tell the team"]


def test_field_labels_fall_back_to_the_id():
    form = _example()
    del form["components"][4]["label"]          # ChoicePicker: label is optional
    form["components"][3]["label"] = "   "      # blank
    labels = service.field_labels(service.clean_form(form))
    assert labels == ["Release name", "due", "kind", "Tell the team"]


def test_field_labels_of_no_form():
    assert service.field_labels(None) == []


def test_guide_lists_every_component():
    guide = service.form_guide()
    assert set(guide) == {"instructions_md", "catalog", "example"}
    assert guide["catalog"]["catalogId"] == CATALOG_ID
    assert set(guide["catalog"]["components"]) == FORM_COMPONENTS
    for name in guide["catalog"]["components"]:
        assert f"`{name}`" in guide["instructions_md"]
    assert guide["example"] == EXAMPLE
    service.clean_form(copy.deepcopy(guide["example"]))


def test_clean_answer_data():
    assert service.clean_answer_data({"na\x00me": ["a\x00"]}) == {"name": ["a"]}
    overhead = len(json.dumps({"t": ""}, separators=(",", ":")))
    service.clean_answer_data({"t": "a" * (MAX_ANSWER_DATA_BYTES - overhead)})  # exactly 16 KB is allowed
    with pytest.raises(HTTPException) as caught:
        service.clean_answer_data({"t": "a" * (MAX_ANSWER_DATA_BYTES - overhead + 1)})
    assert caught.value.status_code == 422
    assert caught.value.detail == "too_large"
