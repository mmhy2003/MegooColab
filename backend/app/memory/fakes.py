"""Deterministic stand-ins for the memory's model calls in fake mode (tests, e2e). No network."""

import json
import re

from app.ai import client as ai
from app.core.config import get_settings

_UNTRUSTED = re.compile(r'<untrusted source="[^"]*">\n(.*?)\n</untrusted>', re.DOTALL)
MAX_FAKE_CONCLUSIONS = 5
MIN_WORDS = 4


def _untrusted_text(messages: list[dict]) -> str:
    return "\n".join(_UNTRUSTED.findall(messages[-1]["content"]))


def fake_extraction(messages: list[dict]) -> str:
    """Every sentence of at least four words (up to five) becomes a conclusion about E1."""
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", _untrusted_text(messages))]
    picked = [s for s in sentences if len(s.split()) >= MIN_WORDS][:MAX_FAKE_CONCLUSIONS]
    return json.dumps({"conclusions": [{"entity": "E1", "text": s} for s in picked]})


def fake_answering(messages: list[dict]) -> str:
    """Answers with the first conclusion offered (C1), or says it does not know."""
    for line in _untrusted_text(messages).splitlines():
        if line.startswith("C1: "):
            text = line[4:].rsplit(" (", 1)[0]
            return json.dumps({"answer": f"From memory: {text}", "cited": ["C1"]})
    return json.dumps({"answer": "I don't know.", "cited": []})


def register() -> None:
    if get_settings().ai_fake:
        ai.FAKE_COMPLETIONS.setdefault("extraction", fake_extraction)
        ai.FAKE_COMPLETIONS.setdefault("answering", fake_answering)


register()
