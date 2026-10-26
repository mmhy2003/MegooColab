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


_LINE = re.compile(r"^(C\d+): (.*) \((observed|deduced|induced|correction)[^)]*\)( \[pinned\])?$")


def fake_dreaming(messages: list[dict]) -> str:
    """Duplicates are replaced by one text; any two conclusions sharing a word of six or more letters induce
    "Pattern: <word>" (confidence 0.6); the card is the first three texts."""
    lines = [m.groups() for m in map(_LINE.match, _untrusted_text(messages).splitlines()) if m]
    replace, induce, seen = [], [], {}
    for cid, text, _kind, _pinned in lines:
        seen.setdefault(text, []).append(cid)
    for text, ids in seen.items():
        if len(ids) > 1:
            replace.append({"ids": ids, "text": text})
    words = {cid: {w.lower() for w in re.findall(r"[A-Za-z]{6,}", text)} for cid, text, _k, _p in lines}
    for i, (a, *_rest) in enumerate(lines):
        for b, *_more in lines[i + 1 :]:
            shared = sorted(words[a] & words[b])
            if shared:
                induce.append({"premises": [a, b], "text": f"Pattern: {shared[0]}", "confidence": 0.6})
    card = "; ".join(text for _c, text, _k, _p in lines[:3])
    return json.dumps({"replace": replace, "deduce": [], "induce": induce[:20], "card": card})


def register() -> None:
    if get_settings().ai_fake:
        ai.FAKE_COMPLETIONS.setdefault("extraction", fake_extraction)
        ai.FAKE_COMPLETIONS.setdefault("answering", fake_answering)
        ai.FAKE_COMPLETIONS.setdefault("dreaming", fake_dreaming)


register()
