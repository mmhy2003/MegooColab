"""MegooColab's A2UI catalog, checked with the a2ui-core validator."""

import copy
import json
from pathlib import Path

import pytest
from a2ui.core import (
    STRICT_VALIDATION,
    A2uiError,
    A2uiIntegrityError,
    A2uiValidationError,
    Catalog,
    MessageProcessor,
    MessageProcessorOptions,
)

import app.a2ui

CATALOG_PATH = Path(app.a2ui.__file__).with_name("catalog.json")
CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1"

COMPONENTS = {
    "Column", "Row", "Card", "Divider", "Text",
    "TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput",
    "Tabs", "List", "StatTile", "TaskLink",
}
FUNCTIONS = {"required", "regex", "length", "numeric", "email"}

# The plan's example form. a2ui-core names the checks property "@checks".
EXAMPLE = {
    "components": [
        {"id": "root", "component": "Column", "children": ["intro", "name", "due", "kind", "notify"]},
        {"id": "intro", "component": "Text", "text": "A few details about the release."},
        {"id": "name", "component": "TextField", "label": "Release name", "value": {"@path": "/name"},
         "variant": "shortText",
         "@checks": [{"condition": {"@call": "required", "args": {"value": {"@path": "/name"}}},
                      "message": "A name is needed"}]},
        {"id": "due", "component": "DateTimeInput", "label": "Due date", "value": {"@path": "/due"},
         "enableDate": True, "enableTime": False},
        {"id": "kind", "component": "ChoicePicker", "label": "Kind", "variant": "mutuallyExclusive",
         "options": [{"label": "Patch", "value": "patch"}, {"label": "Minor", "value": "minor"}],
         "value": {"@path": "/kind"}},
        {"id": "notify", "component": "CheckBox", "label": "Tell the team", "value": {"@path": "/notify"}},
    ],
    "data": {"name": "", "due": "", "kind": ["patch"], "notify": True},
}

# The plan's example card (contract C3): tiles, tabs and a template list of task links.
CARD = {
    "components": [
        {"id": "root", "component": "Column", "children": ["tiles", "tabs"]},
        {"id": "tiles", "component": "Row", "children": ["passed", "failed", "time"]},
        {"id": "passed", "component": "StatTile", "label": "Passed", "value": "412", "tone": "good"},
        {"id": "failed", "component": "StatTile", "label": "Failed", "value": "3", "caption": "2 new since Monday",
         "tone": "bad"},
        {"id": "time", "component": "StatTile", "label": "Run time", "value": "4m 12s"},
        {"id": "tabs", "component": "Tabs",
         "tabs": [{"title": "Failing", "child": "failing"}, {"title": "Notes", "child": "notes"}]},
        {"id": "failing", "component": "List", "children": {"componentId": "row", "path": "/failing"}},
        {"id": "row", "component": "TaskLink", "task": {"@path": "key"}, "label": {"@path": "title"}},
        {"id": "notes", "component": "Text", "text": "Two of the failures are **flaky**."},
    ],
    "data": {"failing": [{"key": "MC-181", "title": "Login times out"}, {"key": "MC-182", "title": "Export is empty"}]},
}


def _catalog_doc() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _message(components: list, data: dict | None) -> dict:
    return {"version": "1.0",
            "createSurface": {"surfaceId": "form-0123456789ab", "catalogId": CATALOG_ID,
                              "components": components, "dataModel": data or {}}}


def _validate(components: list, data: dict | None = None) -> None:
    catalog = Catalog.from_json(_catalog_doc())
    processor = MessageProcessor([catalog], options=MessageProcessorOptions(validation_config=STRICT_VALIDATION))
    processor.process_messages([_message(components, data)])


def test_catalog_has_exactly_our_components_and_functions():
    doc = _catalog_doc()
    assert doc["catalogId"] == CATALOG_ID
    assert doc["protocolVersion"] == "1.0"
    assert set(doc["components"]) == COMPONENTS
    assert set(doc["functions"]) == FUNCTIONS


def test_textfield_has_no_obscured_variant():
    props = Catalog.from_json(_catalog_doc()).resolved_component_schema("TextField")
    variants = json.dumps(props)
    assert '"shortText"' in variants and '"longText"' in variants and '"number"' in variants
    assert "obscured" not in variants


def test_library_accepts_a_valid_form():
    _validate(EXAMPLE["components"], EXAMPLE["data"])


def test_library_reports_a_dangling_id_by_component_and_field():
    components = copy.deepcopy(EXAMPLE["components"])
    components[0]["children"].append("ghost")
    with pytest.raises(A2uiIntegrityError) as caught:
        _validate(components, EXAMPLE["data"])
    # a2ui-core gives integrity errors no path and no details: the message names the component and the field.
    assert caught.value.path is None and caught.value.details == []
    assert "'root'" in caught.value.message and "'ghost'" in caught.value.message
    assert "children[5]" in caught.value.message


def test_library_reports_a_schema_error_with_a_path():
    components = copy.deepcopy(EXAMPLE["components"])
    components[2]["variant"] = "obscured"
    with pytest.raises(A2uiValidationError) as caught:
        _validate(components, EXAMPLE["data"])
    detail = caught.value.details[0]
    assert detail.path == "components.name.variant"
    assert "obscured" in detail.message


def test_library_rejects_a_button():
    components = copy.deepcopy(EXAMPLE["components"])
    components[0]["children"].append("send")
    components.append({"id": "send", "component": "Button", "child": "intro", "action": {"event": {"name": "send"}}})
    with pytest.raises(A2uiError) as caught:
        _validate(components, EXAMPLE["data"])
    assert caught.value.details[0].path == "components.send.component"
    assert "Button" in caught.value.details[0].message


def test_library_rejects_a_left_out_function():
    components = copy.deepcopy(EXAMPLE["components"])
    components[2]["@checks"][0]["condition"]["@call"] = "formatString"
    with pytest.raises(A2uiValidationError) as caught:
        _validate(components, EXAMPLE["data"])
    assert caught.value.details[0].path == "components.name.@checks.0.condition"


def test_library_accepts_a_card():
    _validate(CARD["components"], CARD["data"])


def test_library_accepts_a_template_list():
    components = [
        {"id": "root", "component": "List", "children": {"componentId": "row", "path": "/items"},
         "direction": "vertical", "align": "stretch"},
        {"id": "row", "component": "TaskLink", "task": {"@path": "key"}, "label": {"@path": "title"}},
    ]
    _validate(components, {"items": [{"key": "MC-1", "title": "One"}, {"key": "MC-2", "title": "Two"}]})


def test_library_rejects_a_bad_tone():
    components = copy.deepcopy(CARD["components"])
    components[2]["tone"] = "red"
    with pytest.raises(A2uiValidationError) as caught:
        _validate(components, CARD["data"])
    assert "tone" in caught.value.details[0].path


def test_library_rejects_more_than_the_tab_shape():
    components = copy.deepcopy(CARD["components"])
    del components[5]["tabs"][1]["child"]
    with pytest.raises(A2uiError):
        _validate(components, CARD["data"])
