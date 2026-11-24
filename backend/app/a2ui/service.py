"""Agent forms (MC-172), cards (MC-173) and cron panels (MC-174): what an agent sends to ask_human, show_card or
submit_cron_report becomes a validated A2UI v1.0 createSurface message.

The agent writes only `components` and `data`. `wrap` adds the envelope, `validate` runs a2ui-core against
MegooColab's catalog and then our own limits, and `field_labels` names the inputs for the agent's later prompts.
Forms, cards and panels share the catalog but each allows its own components: `clean_form` takes FORM_COMPONENTS,
`clean_card` takes CARD_COMPONENTS, a read-only set without inputs, and a panel takes PANEL_COMPONENTS, the card's
set plus `Chart`.
"""

import copy
import json
import re
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
FORM_COMPONENTS = frozenset({"Column", "Row", "Card", "Divider", "Text", *INPUTS})
CARD_COMPONENTS = frozenset({"Column", "Row", "Card", "Divider", "Text", "Tabs", "List", "StatTile", "TaskLink"})
PANEL_COMPONENTS = CARD_COMPONENTS | {"Chart"}
MAX_CARD_BYTES = 16 * 1024
MAX_PANEL_BYTES = 16 * 1024
MAX_CHARTS = 4
MAX_TABS = 6
MAX_DATA_ITEMS = 50
TASK_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-[1-9][0-9]*$")

_HERE = Path(__file__).parent


class FormError(HTTPException):
    """422 whose detail is the code, then up to MAX_PROBLEMS "path: message" lines."""

    def __init__(self, code: str, problems: Sequence[dict] = ()):
        self.code = code
        self.problems = [{"path": str(p["path"]), "message": str(p["message"])} for p in problems][:MAX_PROBLEMS]
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT,
                         "\n".join([code, *(f"{p['path']}: {p['message']}" for p in self.problems)]))


class CardError(FormError):
    """A card refused: the same 422 as FormError (the code, then up to MAX_PROBLEMS "path: message" lines)."""


class PanelError(FormError):
    """A panel refused: the same 422 as FormError (the code, then up to MAX_PROBLEMS "path: message" lines)."""


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


@cache
def _catalog_doc() -> dict:
    return json.loads((_HERE / "catalog.json").read_text())


@cache
def _catalog() -> Catalog:
    return Catalog.from_json(_catalog_doc())


@cache
def _instructions() -> str:
    return (_HERE / "guide.md").read_text()


@cache
def _example() -> dict:
    return json.loads((_HERE / "example.json").read_text())


@cache
def _card_instructions() -> str:
    return (_HERE / "card_guide.md").read_text()


@cache
def _card_example() -> dict:
    return json.loads((_HERE / "card_example.json").read_text())


def wrap(components: list, data: dict | None, prefix: str = "form") -> dict:
    """The createSurface message for a form, a card or a panel, with a surface id of its own."""
    return {"version": "1.0",
            "createSurface": {"surfaceId": f"{prefix}-" + uuid.uuid4().hex[:12], "catalogId": CATALOG_ID,
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


def _library(message: dict) -> list[dict]:
    """a2ui-core's problems with the message against our catalog; empty when it passes."""
    processor = MessageProcessor([_catalog()], options=MessageProcessorOptions(validation_config=STRICT_VALIDATION))
    try:
        processor.process_messages([message])
    except A2uiError as error:
        return _problems(error)
    return []


def validate(message: dict) -> None:
    """The library's checks against our catalog, then our limits. Raises FormError."""
    if problems := _library(message):
        raise FormError("invalid_form", problems)
    surface = message["createSurface"]
    _check_limits(surface["components"], surface.get("dataModel"))


def _outside(components: list, allowed: frozenset[str]) -> list[dict]:
    """The components whose name is not one of `allowed`, as problems."""
    return [{"path": f"components.{c.get('id')}.component", "message": f"{c.get('component')!r} is not allowed here"}
            for c in components if not (isinstance(c.get("component"), str) and c["component"] in allowed)]


def clean_form(form: Any) -> dict:
    """The agent's {components, data?} as a validated stored message. Raises FormError."""
    if not (isinstance(form, dict) and "components" in form and set(form) <= {"components", "data"}):
        raise FormError("invalid_form", [{"path": "form", "message": "must be {components, data?} and nothing else"}])
    if not (isinstance(form["components"], list) and all(isinstance(c, dict) for c in form["components"])):
        raise FormError("invalid_form", [{"path": "form", "message": "components must be a list of objects"}])
    if not isinstance(form.get("data", {}), dict):
        raise FormError("invalid_form", [{"path": "form", "message": "data must be an object"}])
    form = strip_nul_deep(form)
    if problems := _outside(form["components"], FORM_COMPONENTS):
        raise FormError("invalid_form", problems)
    _check_limits(form["components"], form.get("data"))
    message = wrap(form["components"], form.get("data"))
    validate(message)
    return message


def _long_array(value: Any, path: str = "data") -> str | None:
    """The path of the first array in `value` with more than MAX_DATA_ITEMS items."""
    if isinstance(value, list):
        if len(value) > MAX_DATA_ITEMS:
            return path
        items = enumerate(value)
    elif isinstance(value, dict):
        items = value.items()
    else:
        return None
    for key, item in items:
        if found := _long_array(item, f"{path}.{key}"):
            return found
    return None


def _checked_display(value: Any, name: str, error: type[FormError], allowed: frozenset[str],
                     max_bytes: int) -> tuple[list, dict | None]:
    """The checks every read-only surface (a card, a panel) gets: its shape, NUL stripped, its size, its component
    count, no inputs, only `allowed` components, tabs, task keys, data arrays. Codes are invalid_<name>,
    <name>_with_inputs and too_large; shape problems have the path `name`. Returns (components, data)."""
    invalid = f"invalid_{name}"
    if not (isinstance(value, dict) and "components" in value and set(value) <= {"components", "data"}):
        raise error(invalid, [{"path": name, "message": "must be {components, data?} and nothing else"}])
    if not (isinstance(value["components"], list) and all(isinstance(c, dict) for c in value["components"])):
        raise error(invalid, [{"path": name, "message": "components must be a list of objects"}])
    if not isinstance(value.get("data", {}), dict):
        raise error(invalid, [{"path": name, "message": "data must be an object"}])
    value = strip_nul_deep(value)
    components, data = value["components"], value.get("data")
    if _size(value) > max_bytes:
        raise error("too_large", [{"path": name, "message": f"over {max_bytes} bytes"}])
    if len(components) > MAX_COMPONENTS:
        raise error("too_large", [{"path": "components", "message": f"over {MAX_COMPONENTS} components"}])
    if any(_is_input(c) for c in components):
        raise error(f"{name}_with_inputs")
    if problems := _outside(components, allowed):
        raise error(invalid, problems)
    for c in components:
        if c["component"] == "Tabs" and isinstance(c.get("tabs"), list) and len(c["tabs"]) > MAX_TABS:
            raise error("too_large", [{"path": f"components.{c.get('id')}.tabs", "message": f"over {MAX_TABS} tabs"}])
        task = c.get("task") if c["component"] == "TaskLink" else None
        if isinstance(task, str) and not TASK_KEY.fullmatch(task):
            raise error(invalid, [{"path": f"components.{c.get('id')}.task", "message": "not a task key such as MC-181"}])
    if path := _long_array(data):
        raise error("too_large", [{"path": path, "message": f"over {MAX_DATA_ITEMS} items"}])
    return components, data


def clean_card(card: Any) -> dict:
    """The agent's {components, data?} as a validated, stored card surface. Raises CardError."""
    components, data = _checked_display(card, "card", CardError, CARD_COMPONENTS, MAX_CARD_BYTES)
    message = wrap(components, data, prefix="card")
    if problems := _library(message):
        raise CardError("invalid_card", problems)
    return message


def _points(component: dict) -> str | None:
    """The data-model path a chart's points are bound to, or None when they aren't bound to a path."""
    points = component.get("points")
    path = points.get("@path") if isinstance(points, dict) else None
    return path if isinstance(path, str) else None


def _resolve(data: dict, path: str) -> Any:
    """The value at an absolute JSON pointer in data (~1 is "/", ~0 is "~"), or None when it isn't there."""
    value: Any = data
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            return None
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _chart_problems(components: list, data: dict) -> list[dict]:
    """Each chart's data checked against the panel's own data, as {path, message} problems. A rule whose shape is
    wrong (x not text, series not a list of objects) is skipped: the catalog check after it names that."""
    problems = []
    for c in components:
        at = f"components.{c.get('id')}"
        path = _points(c)
        if path is None or not path.startswith("/"):
            problems.append({"path": f"{at}.points", "message": "must be an absolute path such as /trend"})
            continue
        points = _resolve(data, path)
        if not (isinstance(points, list) and 1 <= len(points) <= MAX_DATA_ITEMS
                and all(isinstance(p, dict) for p in points)):
            problems.append({"path": f"{at}.points",
                             "message": f"{path} is not a list of 1 to {MAX_DATA_ITEMS} objects in data"})
            continue
        x = c.get("x")
        if isinstance(x, str):
            for n, point in enumerate(points):
                if not (isinstance(point.get(x), str) or _is_number(point.get(x))):
                    problems.append({"path": f"{at}.x", "message": f'point {n} of {path} has no text or number under "{x}"'})
                    break
        series = c.get("series")
        if not (isinstance(series, list) and all(isinstance(s, dict) and isinstance(s.get("key"), str) for s in series)):
            continue
        keys = [s["key"] for s in series]
        if len(set(keys)) < len(keys) or x in keys:
            problems.append({"path": f"{at}.series", "message": "series keys must differ from each other and from x"})
        for k, key in enumerate(keys):
            values = [point.get(key) for point in points]
            wrong = next(((n, v) for n, v in enumerate(values) if v is not None and not _is_number(v)), None)
            if wrong is not None:
                problems.append({"path": f"{at}.series.{k}.key",
                                 "message": f'point {wrong[0]} of {path} has {wrong[1]!r} under "{key}", not a number'})
            elif not any(_is_number(v) for v in values):
                problems.append({"path": f"{at}.series.{k}.key", "message": f'no point of {path} has a number under "{key}"'})
    return problems


def clean_panel(panel: Any) -> dict:
    """The agent's {components, data?} as a validated, stored panel surface. Raises PanelError."""
    components, data = _checked_display(panel, "panel", PanelError, PANEL_COMPONENTS, MAX_PANEL_BYTES)
    charts = [c for c in components if c["component"] == "Chart"]
    if len(charts) > MAX_CHARTS:
        raise PanelError("too_large", [{"path": "components", "message": f"over {MAX_CHARTS} charts"}])
    if problems := _chart_problems(charts, data or {}):
        raise PanelError("invalid_panel", problems)
    message = wrap(components, data, prefix="panel")
    if problems := _library(message):
        raise PanelError("invalid_panel", problems)
    return message


def unwrap(message: dict) -> dict:
    """The {components, data} an agent writes, from a stored createSurface message."""
    surface = message["createSurface"]
    return {"components": surface["components"], "data": surface.get("dataModel") or {}}


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


def _catalog_for(allowed: frozenset[str]) -> dict:
    """The catalog cut down to `allowed` components (functions kept)."""
    doc = copy.deepcopy(_catalog_doc())
    doc["components"] = {k: v for k, v in doc["components"].items() if k in allowed}
    one_of = doc["$defs"]["anyComponent"]["oneOf"]
    doc["$defs"]["anyComponent"]["oneOf"] = [r for r in one_of if r["$ref"].rsplit("/", 1)[-1] in allowed]
    return doc


def form_guide() -> dict:
    """What get_form_guide gives an agent: instructions, the form part of the catalog and an example form."""
    return {"instructions_md": _instructions(), "catalog": _catalog_for(FORM_COMPONENTS), "example": _example()}


def card_guide() -> dict:
    """What get_card_guide gives an agent: instructions, the card part of the catalog and an example card."""
    return {"instructions_md": _card_instructions(), "catalog": _catalog_for(CARD_COMPONENTS),
            "example": _card_example()}


def clean_answer_data(data: dict) -> dict:
    """A person's form answer without NUL characters, at most MAX_ANSWER_DATA_BYTES once serialised."""
    data = strip_nul_deep(data)
    if _size(data) > MAX_ANSWER_DATA_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_large")
    return data
