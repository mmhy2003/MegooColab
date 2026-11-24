from typing import Annotated, Any

from pydantic import BeforeValidator


def strip_nul(s: str) -> str:
    """Postgres text and JSONB reject NUL characters."""
    return s.replace("\x00", "")


def strip_nul_deep(value: Any) -> Any:
    """strip_nul on every string of a JSON value: dict keys, list items and nested values."""
    if isinstance(value, str):
        return strip_nul(value)
    if isinstance(value, dict):
        return {strip_nul_deep(k): strip_nul_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul_deep(v) for v in value]
    return value


def _strip_if_str(v: Any) -> Any:
    return strip_nul(v) if isinstance(v, str) else v


# A BeforeValidator, so Field(min_length/max_length) are checked on the stripped text: "\x00" is empty (422).
NoNulStr = Annotated[str, BeforeValidator(_strip_if_str)]
