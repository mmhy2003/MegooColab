from typing import Annotated

from pydantic import AfterValidator


def strip_nul(s: str) -> str:
    """Postgres text and JSONB reject NUL characters."""
    return s.replace("\x00", "")


# Validators run in order, so min_length/max_length (Field) see the stripped text when used with NoNulStr.
NoNulStr = Annotated[str, AfterValidator(strip_nul)]
