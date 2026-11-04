"""A draft as Markdown blocks, and an agent turn's changes to it as marks the person keeps or undoes.

A block is a heading, paragraph, list, table or fenced code block: text between blank lines, except that a fence
keeps its blank lines. A turn is the draft before the agent's change, the agent's whole new text, and the block diff
between them; each non-equal part of the diff is a mark, numbered in order, with a status open, kept or undone.
"""

from app.kb.service import opcodes

FENCES = ("```", "~~~")
CHANGE = {"insert": "added", "delete": "removed", "replace": "changed"}


def split_blocks(md: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in md.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        if fence is not None:
            current.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current).rstrip())
                current = []
            continue
        opener = next((f for f in FENCES if stripped.startswith(f)), None)
        if opener is not None:
            fence = opener
        current.append(line.rstrip())
    if current:
        blocks.append("\n".join(current).rstrip())
    return [b for b in blocks if b]


def join_blocks(blocks: list[str]) -> str:
    return "\n\n".join(blocks)


def new_turn(request: str, before_md: str, after_md: str) -> dict | None:
    """The marks of an agent turn that changed `before_md` into `after_md`, all open; None if nothing changed."""
    before, after = split_blocks(before_md), split_blocks(after_md)
    ops = [list(op) for op in opcodes(before, after)]
    changes = sum(1 for op in ops if op[0] != "equal")
    if not changes:
        return None
    return {"request": request, "before": before, "after": after, "ops": ops,
            "status": {str(i): "open" for i in range(changes)}}


def mark_kind(tag: str) -> str:
    return CHANGE[tag]


def _walk(turn: dict):
    """(mark id or None, status, before blocks, after blocks) for each part of the turn's diff."""
    n = 0
    for tag, a1, a2, b1, b2 in turn["ops"]:
        before, after = turn["before"][a1:a2], turn["after"][b1:b2]
        if tag == "equal":
            yield None, tag, "kept", before, after
            continue
        yield n, tag, turn["status"][str(n)], before, after
        n += 1


def compose(turn: dict) -> str:
    """The draft as the turn leaves it: undone marks take what was there before, the rest what the agent wrote."""
    blocks: list[str] = []
    for _, _, status, before, after in _walk(turn):
        blocks.extend(before if status == "undone" else after)
    return join_blocks(blocks)


def segments(turn: dict | None, body_md: str) -> list[dict]:
    """The draft for display: settled text, and each open mark with what it changed."""
    if turn is None:
        return [{"kind": "text", "md": body_md}] if body_md else []
    out: list[dict] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            out.append({"kind": "text", "md": join_blocks(pending)})
            pending.clear()

    for mark_id, tag, status, before, after in _walk(turn):
        if status == "open":
            flush()
            out.append({"kind": "mark", "id": mark_id, "change": mark_kind(tag), "request": turn["request"],
                        "old_md": join_blocks(before), "new_md": join_blocks(after)})
        else:
            pending.extend(before if status == "undone" else after)
    flush()
    return out


def open_count(turn: dict | None) -> int:
    return sum(1 for s in (turn or {}).get("status", {}).values() if s == "open")
