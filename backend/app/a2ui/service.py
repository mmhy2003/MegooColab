"""Agent forms (MC-172): what an agent sends to ask_human becomes a validated A2UI v1.0 createSurface message.

The agent writes only `components` and `data`. `wrap` adds the envelope, `validate` runs a2ui-core against
MegooColab's catalog and then our own limits, and `field_labels` names the inputs for the agent's later prompts.
"""

import copy
import json
import uuid
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

from a2ui.core import STRICT_VALIDATION, A2uiError, Catalog, MessageProcessor, MessageProcessorOptions
from fastapi import HTTPException, status

from app.core.text import strip_nul_deep

CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1"
INPUTS = frozenset({"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"})
MAX_FORM_BYTES = 32 * 1024
MAX_COMPONENTS = 60
MAX_INPUTS = 20
MAX_PROBLEMS = 10
MAX_ANSWER_DATA_BYTES = 16 * 1024
# Catalog entries for cards (MC-173), left out of the form guide.
_CARD_ONLY = frozenset({"Tabs", "List", "StatTile", "TaskLink"})

_HERE = Path(__file__).parent


class FormError(HTTPException):
    """422 whose detail is the code, then up to MAX_PROBLEMS "path: message" lines."""

    def __init__(self, code: str, problems: Sequence[dict] = ()):
        self.code = code
        self.problems = [{"path": str(p["path"]), "message": str(p["message"])} for p in problems][:MAX_PROBLEMS]
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT,
                         "\n".join([code, *(f"{p['path']}: {p['message']}" for p in self.problems)]))


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


@cache
def _catalog_doc() -> dict:
    return json.loads((_HERE / "catalog.json").read_text())


@cache
def _catalog() -> Catalog:
    return Catalog.from_json(_catalog_doc())


@cache
def _form_catalog() -> dict:
    """The catalog without the card entries."""
    doc = copy.deepcopy(_catalog_doc())
    doc["components"] = {k: v for k, v in doc["components"].items() if k not in _CARD_ONLY}
    any_component = doc["$defs"]["anyComponent"]
    any_component["oneOf"] = [r for r in any_component["oneOf"] if r["$ref"].rsplit("/", 1)[-1] not in _CARD_ONLY]
    return doc


@cache
def _instructions() -> str:
    return (_HERE / "guide.md").read_text()


@cache
def _example() -> dict:
    return json.loads((_HERE / "example.json").read_text())


def wrap(components: list, data: dict | None) -> dict:
    """The createSurface message for a form, with a surface id of its own."""
    return {"version": "1.0",
            "createSurface": {"surfaceId": "form-" + uuid.uuid4().hex[:12], "catalogId": CATALOG_ID,
                              "components": components, "dataModel": data or {}}}


def _problems(error: A2uiError) -> list[dict]:
    """The library's errors as {path, message}. Integrity errors (a dangling id, no root) carry no path or
    details, only a message naming the component and field."""
    if error.details:
        return [{"path": d.path or "components", "message": d.message} for d in error.details]
    return [{"path": error.path or "components", "message": error.message}]


def _is_input(component: dict) -> bool:
    name = component.get("component")
    return isinstance(name, str) and name in INPUTS


def _check_limits(components: list, data: dict | None) -> None:
    """Our limits on a form: its size, its component and input counts, and at least one input."""
    form = {"components": components, **({"data": data} if data else {})}
    if _size(form) > MAX_FORM_BYTES:
        raise FormError("too_large", [{"path": "form", "message": f"over {MAX_FORM_BYTES} bytes"}])
    if len(components) > MAX_COMPONENTS:
        raise FormError("too_large", [{"path": "components", "message": f"over {MAX_COMPONENTS} components"}])
    inputs = sum(1 for c in components if _is_input(c))
    if inputs > MAX_INPUTS:
        raise FormError("too_large", [{"path": "components", "message": f"over {MAX_INPUTS} inputs"}])
    if inputs == 0:
        raise FormError("form_without_inputs")


def validate(message: dict) -> None:
    """The library's checks against our catalog, then our limits. Raises FormError."""
    processor = MessageProcessor([_catalog()], options=MessageProcessorOptions(validation_config=STRICT_VALIDATION))
    try:
        processor.process_messages([message])
    except A2uiError as error:
        raise FormError("invalid_form", _problems(error)) from None
    surface = message["createSurface"]
    _check_limits(surface["components"], surface.get("dataModel"))


def clean_form(form: Any) -> dict:
    """The agent's {components, data?} as a validated stored message. Raises FormError."""
    if not (isinstance(form, dict) and "components" in form and set(form) <= {"components", "data"}):
        raise FormError("invalid_form", [{"path": "form", "message": "must be {components, data?} and nothing else"}])
    if not (isinstance(form["components"], list) and all(isinstance(c, dict) for c in form["components"])):
        raise FormError("invalid_form", [{"path": "form", "message": "components must be a list of objects"}])
    if not isinstance(form.get("data", {}), dict):
        raise FormError("invalid_form", [{"path": "form", "message": "data must be an object"}])
    form = strip_nul_deep(form)
    _check_limits(form["components"], form.get("data"))
    message = wrap(form["components"], form.get("data"))
    validate(message)
    return message


def field_labels(message: dict | None) -> list[str]:
    """Each input's label in component order, or its id when the label is missing or blank."""
    if not message:
        return []
    labels = []
    for c in message["createSurface"]["components"]:
        if _is_input(c):
            label = c.get("label")
            labels.append(label.strip() if isinstance(label, str) and label.strip() else str(c.get("id")))
    return labels


def guide() -> dict:
    """What get_form_guide gives an agent: instructions, the catalog and an example form."""
    return {"instructions_md": _instructions(), "catalog": _form_catalog(), "example": _example()}


def clean_answer_data(data: dict) -> dict:
    """A person's form answer without NUL characters, at most MAX_ANSWER_DATA_BYTES once serialised."""
    data = strip_nul_deep(data)
    if _size(data) > MAX_ANSWER_DATA_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_large")
    return data
