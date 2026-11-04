"""Secret values replaced by their names: `[NAME]`. Values shorter than MIN_LENGTH are left alone (blanking them would
mangle ordinary text); the longest value goes first, so one that contains another is blanked whole. A value is also
blanked as it commonly appears written into other text: trimmed (a value pasted with a newline), JSON-escaped, and
percent-encoded (in a URL or a query). The runner does the same (runner/internal/mask)."""

import json
from urllib.parse import quote, quote_plus

MIN_LENGTH = 4


def forms(value: str) -> set[str]:
    """The ways a value commonly appears in text, each at least MIN_LENGTH long."""
    out = {value, value.strip(), json.dumps(value)[1:-1], quote(value, safe=""), quote(value), quote_plus(value)}
    return {f for f in out if len(f) >= MIN_LENGTH}


def _pairs(secrets: dict[str, str]) -> list[tuple[str, str]]:
    pairs = {(f, f"[{k}]") for k, v in secrets.items() if len(v) >= MIN_LENGTH for f in forms(v)}
    return sorted(pairs, key=lambda p: (-len(p[0]), p[0]))


def blank(text: str, secrets: dict[str, str]) -> str:
    for value, label in _pairs(secrets):
        text = text.replace(value, label)
    return text


def blank_json(obj, secrets: dict[str, str]):
    """`blank` in every string of nested dicts and lists; keys are left as they are."""
    if isinstance(obj, str):
        return blank(obj, secrets)
    if isinstance(obj, list):
        return [blank_json(v, secrets) for v in obj]
    if isinstance(obj, dict):
        return {k: blank_json(v, secrets) for k, v in obj.items()}
    return obj
