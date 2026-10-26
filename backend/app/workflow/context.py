"""Prompt assembly: the text MegooColab sends to a coding agent for one workflow run.

Task text, thread items, answers, comments and findings are untrusted (NFR-3): each is wrapped in
<untrusted source="...">, and the content cannot close the wrapper from inside.
"""

import logging
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import Project
from app.tasks.activity import activity_items
from app.tasks.models import Task
from app.workflow import methodology
from app.workflow.models import (
    DocKind,
    DocStatus,
    MethodologyVersion,
    RunRole,
    WorkflowDocument,
)

log = logging.getLogger(__name__)

ContextProvider = Callable[[AsyncSession, Task, RunRole], Awaitable[str | None]]
# Plans 4 and 5 append providers here; each returns a section (or None) to add after the built-in ones.
context_providers: list[ContextProvider] = []

ROLE_KEY: dict[RunRole, str] = {
    RunRole.brainstorm: "brainstorm",
    RunRole.plan: "plan",
    RunRole.implement: "build_implement",
    RunRole.step_review: "build_step_review",
    RunRole.step_fix: "build_step_fix",
    RunRole.final_review: "review_final",
    RunRole.final_fix: "review_fix",
    RunRole.finish: "finish",
}

MAX_PROMPT_CHARS = 60_000
MAX_THREAD_ITEMS = 50
MAX_RESUME_CHARS = 8_000

BUILD_ROLES = {
    RunRole.implement, RunRole.step_review, RunRole.step_fix,
    RunRole.final_review, RunRole.final_fix, RunRole.finish,
}
STEP_ROLES = {RunRole.implement, RunRole.step_fix, RunRole.step_review}
FIX_ROLES = {RunRole.step_fix, RunRole.final_fix}

# every angle bracket (ASCII, fullwidth and small forms) becomes an entity, so no tag can form at all
_BRACKET_TABLE = str.maketrans(
    {"<": "&lt;", ">": "&gt;", "＜": "&lt;", "＞": "&gt;", "﹤": "&lt;", "﹥": "&gt;"}
)
_CLOSE = "\n</untrusted>"


def _escape(text: str) -> str:
    """Neutralise text for the prompt: drop Unicode format (Cf) characters, escape every angle bracket."""
    return "".join(c for c in text if unicodedata.category(c) != "Cf").translate(_BRACKET_TABLE)


def wrap_untrusted(source: str, text: str) -> str:
    return f'<untrusted source="{source}">\n{_escape(text)}{_CLOSE}'


def _cut(text: str, overshoot: int) -> str:
    """Remove at least `overshoot` chars (plus a margin for escaping growth) from the end."""
    return text[: max(0, len(text) - overshoot - 100)]


def _finding_line(f: dict) -> str:
    where = str(f.get("file") or "")
    if where and f.get("line"):
        where = f"{where}:{f['line']}"
    return f"- [{f.get('severity', 'minor')}] {where or '(no file)'}: {f.get('summary', '')}"


def _findings_text(findings: list[dict]) -> str:
    return "\n".join(_finding_line(f) for f in findings)


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _question_text(q: Any) -> str:
    """A question as its body, its choices as labels and, once answered, the answer."""
    choices = _get(q, "choices") or []
    labels = {_get(c, "id"): _get(c, "label") for c in choices}
    lines = [str(_get(q, "body") or "")]
    if choices:
        lines.append("Choices: " + ", ".join(str(_get(c, "label") or _get(c, "id")) for c in choices))
    choice, text = _get(q, "answer_choice"), _get(q, "answer_text")
    if choice or text:
        answer = str(labels.get(choice) or choice or "")
        lines.append("Answer: " + " — ".join(p for p in (answer, str(text or "")) if p))
    return "\n".join(lines)


def _item_text(item: Any) -> str:
    who = getattr(getattr(item, "actor", None), "name", None) or "system"
    if item.type == "question":
        body = _question_text(_get(item, "question"))
    else:
        body = getattr(item, "body_md", None) or ""
    return f"[{item.type} by {who} at {item.at:%Y-%m-%d %H:%M}]\n{body}"


async def _thread(db: AsyncSession, task: Task) -> list[str]:
    # events are bookkeeping, not conversation: fetch wider so they cannot crowd out the latest 50 items
    items = await activity_items(db, task, limit=MAX_THREAD_ITEMS * 4)
    texts = [_item_text(i) for i in items if i.type in ("comment", "question")]
    return texts[-MAX_THREAD_ITEMS:]


async def _approved(db: AsyncSession, task_id: uuid.UUID, kind: DocKind) -> WorkflowDocument | None:
    return (
        await db.execute(
            select(WorkflowDocument)
            .where(
                WorkflowDocument.task_id == task_id,
                WorkflowDocument.kind == kind,
                WorkflowDocument.status == DocStatus.approved,
            )
            .order_by(WorkflowDocument.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _provided(db: AsyncSession, task: Task, role: RunRole, provider: ContextProvider) -> str | None:
    """A provider's section; a failing provider is logged and skipped, never fails the run it builds."""
    try:
        async with db.begin_nested():
            return await provider(db, task, role)
    except Exception:
        log.exception("context provider %s failed", getattr(provider, "__name__", provider))
        return None


async def build_prompt(
    db: AsyncSession,
    task: Task,
    role: RunRole,
    *,
    step: int | None = None,
    findings: list[dict] | None = None,
    previous_findings: list[dict] | None = None,
    extra_sections: list[str] | None = None,
    key_override: str | None = None,
) -> tuple[str, MethodologyVersion]:
    role = RunRole(role)
    meth = await methodology.current(db, key_override or ROLE_KEY[role])
    key = f"{(await db.get(Project, task.project_id)).key}-{task.number}"
    thread = await _thread(db, task)

    design = await _approved(db, task.id, DocKind.design) if role == RunRole.plan or role in BUILD_ROLES else None
    plan = await _approved(db, task.id, DocKind.plan) if role in BUILD_ROLES else None
    design_body = design.body_md if design and role == RunRole.plan else None

    docs: list[str] = []  # reference sections after the thread
    for title, doc, name in (("Approved design", design, "design"), ("Approved plan", plan, "plan")):
        if doc is not None and role in BUILD_ROLES:
            docs.append(
                f"## {title}\nThe approved {name} is at `.megoocolab/{name}.md` in your worktree "
                f"(read-only). Read it before you start."
            )

    step_section = None
    if role in STEP_ROLES and step is not None:
        if plan is None:
            raise ValueError("no approved plan")
        steps = plan.steps or []
        step_section = f"## Step {step} of {len(steps)}"
        if 1 <= step <= len(steps):
            s = steps[step - 1]
            # approved by a human, so not wrapped; escaped so it cannot open a fake wrapper
            step_section += _escape(f"\n{s.get('title', '')}\n\n{s.get('detail', '')}").rstrip()

    finding_lines = [_finding_line(f) for f in findings] if role in FIX_ROLES and findings is not None else None
    shown = len(finding_lines) if finding_lines is not None else 0
    # a re-review checks that the previous round's findings were addressed
    prev_lines = [_finding_line(f) for f in previous_findings] if previous_findings else None
    prev_shown = len(prev_lines) if prev_lines is not None else 0

    extra = [s for p in context_providers if (s := await _provided(db, task, role, p))]

    description = task.description_md or ""
    dropped = 0
    notes: set[str] = set()

    def render() -> str:
        parts = [meth.body_md.rstrip()]
        desc_note = "\n(Description truncated to fit the prompt size limit.)" if "desc" in notes else ""
        parts.append(
            f"## Task {key}\n"
            + wrap_untrusted("task", f"{task.title}\n\n{description}".rstrip())
            + desc_note
        )
        thread_note = f"\n({dropped} older thread items omitted to fit the prompt size limit.)" if dropped else ""
        body = wrap_untrusted("thread", "\n\n".join(thread)) if thread else "(no thread items)"
        parts.append("## Thread\n" + body + thread_note)
        if role == RunRole.plan and design_body is not None:
            note = "\n(Design truncated to fit the prompt size limit.)" if "design" in notes else ""
            parts.append("## Approved design\n" + _escape(design_body) + note)
        parts.extend(docs)
        if step_section:
            parts.append(step_section)
        if finding_lines is not None:
            omitted = len(finding_lines) - shown
            note = f"\n({omitted} more findings omitted to fit the prompt size limit.)" if omitted else ""
            parts.append("## Review findings\n" + wrap_untrusted("findings", "\n".join(finding_lines[:shown])) + note)
        if prev_lines is not None:
            omitted = len(prev_lines) - prev_shown
            note = f"\n({omitted} more findings omitted to fit the prompt size limit.)" if omitted else ""
            parts.append(
                "## Previous review findings (verify each was addressed)\n"
                + wrap_untrusted("previous_findings", "\n".join(prev_lines[:prev_shown]))
                + note
            )
        parts.extend(extra_sections or [])  # MegooColab's own text (e.g. the finishing option): not wrapped
        parts.extend(extra)
        return "\n\n".join(parts)

    prompt = render()
    while len(prompt) > MAX_PROMPT_CHARS:
        over = len(prompt) - MAX_PROMPT_CHARS
        if extra:  # optional context (the Knowledge Base) goes before anything about the task itself
            extra.pop()
        elif thread:
            thread.pop(0)
            dropped += 1
        elif prev_shown:
            prev_shown -= 1
        elif shown:
            shown -= 1
        elif design_body:
            design_body = _cut(design_body, over)
            notes.add("design")
        elif description:
            description = _cut(description, over)
            notes.add("desc")
        else:
            break
        prompt = render()
    if len(prompt) > MAX_PROMPT_CHARS:
        # methodology / providers alone are too big: slice, but never leave a wrapper open
        prompt = prompt[: MAX_PROMPT_CHARS - len(_CLOSE)]
        body = prompt[len(meth.body_md.rstrip()):]  # the methodology prose mentions the tags itself
        if body.count("<untrusted") > body.count("</untrusted"):
            prompt += _CLOSE
    return prompt, meth


def _bounded(prefix: str, source: str, content: str, suffix: str = "") -> str:
    """prefix + untrusted block + suffix, with the block's content cut so the whole is <= 8,000 chars."""
    overhead = len(prefix) + len(suffix) + len(wrap_untrusted(source, ""))
    escaped = _escape(content)
    budget = MAX_RESUME_CHARS - overhead
    if len(escaped) > budget:
        escaped = escaped[: max(0, budget - 15)] + " …[truncated]"
    return f'{prefix}<untrusted source="{source}">\n{escaped}\n</untrusted>{suffix}'


NUDGE_DEFAULT = (
    "Your last run ended without asking a question or submitting your design. Continue: ask the human "
    "with ask_human, or submit your design with submit_design."
)


def resume_text(kind: str, payload: Any) -> str:
    """The short text sent when a session is resumed. Payload by kind:
    answer {choice_label?, text?}; rejection {comment, kind: "design"|"plan"};
    nudge {text?} (or a str); findings: list of finding dicts."""
    if kind == "answer":
        parts = []
        if payload.get("choice_label"):
            parts.append(f"Chosen: {payload['choice_label']}")
        if payload.get("text"):
            parts.append(str(payload["text"]))
        return _bounded("The human answered your question.\n", "answer", "\n".join(parts) or "(no answer text)")
    if kind == "rejection":
        tool = "submit_plan" if payload.get("kind") == "plan" else "submit_design"
        return _bounded(
            f"The reviewer rejected your {payload.get('kind', 'design')}.\n",
            "rejection",
            str(payload.get("comment") or "(no comment)"),
            f"\nRevise and resubmit with {tool}.",
        )
    if kind == "nudge":
        text = payload if isinstance(payload, str) else (payload or {}).get("text")
        return (text or NUDGE_DEFAULT)[:MAX_RESUME_CHARS]
    if kind == "findings":
        return _bounded(
            "Review findings to address:\n", "findings", _findings_text(payload),
            "\nFix these, then complete the step again.",
        )
    raise ValueError(f"unknown resume kind {kind!r}")
