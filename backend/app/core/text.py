from typing import Annotated, Any

from pydantic import BeforeValidator


def strip_nul(s: str) -> str:
    """Postgres text and JSONB reject NUL characters."""
    return s.replace("\x00", "")


def _strip_if_str(v: Any) -> Any:
    return strip_nul(v) if isinstance(v, str) else v


# A BeforeValidator, so Field(min_length/max_length) are checked on the stripped text: "\x00" is empty (422).
NoNulStr = Annotated[str, BeforeValidator(_strip_if_str)]
