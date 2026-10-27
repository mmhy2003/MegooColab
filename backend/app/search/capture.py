"""Keeps the search index current without touching every write path (Plan 9).

`after_flush` notes which searchable items a transaction changed (a comment or an activity event counts as a
change to its task). `before_commit` queues one deduplicated `search.sync` job per item, in the same transaction,
so a change is indexed only once it is committed and a slow or absent Meilisearch never slows a save. Deleted
projects and Knowledge Base spaces also queue `search.purge`, for the rows their `ON DELETE CASCADE` removes.
"""

from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.a2a.models import Question
from app.agents.models import Agent, AgentBinding
from app.auth.models import User
from app.jobs.models import Job
from app.jobs.queue import CHANNEL
from app.kb.models import KbDocument, KbSpace
from app.projects.models import BoardColumn, Label, Project
from app.tasks.models import Comment, Task, TaskEvent, task_labels
from app.teams.models import Team, TeamMember

# index updates outlast any Meilisearch outage: the backoff caps at an hour, so this is about six weeks of retries
MAX_ATTEMPTS = 1000
DIRTY = "search_dirty"
PURGE = "search_purge"
SKIP = "search_skip"

# model -> the (kind, id) items a change to one of its rows affects
_AFFECTS: dict[type, Any] = {
    Task: lambda o: [("task", o.id)],
    Comment: lambda o: [("task", o.task_id)],
    TaskEvent: lambda o: [("task", o.task_id)],
    KbDocument: lambda o: [("document", o.id)],
    Project: lambda o: [("project", o.id)],
    Team: lambda o: [("team", o.id)],
    TeamMember: lambda o: [("team", o.team_id), ("person", o.user_id)],
    User: lambda o: [("person", o.id)],
    Agent: lambda o: [("agent", o.id)],
    AgentBinding: lambda o: [("agent", o.agent_id)],
    Question: lambda o: [("question", o.id)],
}


def _after_flush(session: Session, _ctx) -> None:
    if session.info.get(SKIP):
        return
    dirty: set = session.info.setdefault(DIRTY, set())
    purge: set = session.info.setdefault(PURGE, set())
    for obj in (*session.new, *session.dirty, *session.deleted):
        affects = _AFFECTS.get(type(obj))
        if affects is None:
            continue
        for kind, id in affects(obj):
            if id is not None:
                dirty.add((kind, str(id)))
    for obj in session.deleted:
        if isinstance(obj, Project):
            purge.add(("project_id", str(obj.id)))
        elif isinstance(obj, KbSpace):
            purge.add(("readers", f"space:{obj.id}"))


def _before_commit(session: Session) -> None:
    # commit flushes only after this hook runs: flush now so changes still pending are noted too
    session.flush()
    dirty = session.info.pop(DIRTY, set())
    purge = session.info.pop(PURGE, set())
    if session.info.get(SKIP) or not (dirty or purge):
        return
    rows = [
        {"kind": "search.sync", "payload": {"kind": kind, "id": id}, "dedupe_key": f"search.sync:{kind}:{id}",
         "max_attempts": MAX_ATTEMPTS}
        for kind, id in sorted(dirty)
    ] + [
        {"kind": "search.purge", "payload": {"field": field, "value": value},
         "dedupe_key": f"search.purge:{field}:{value}", "max_attempts": MAX_ATTEMPTS}
        for field, value in sorted(purge)
    ]
    session.execute(
        insert(Job).values(rows)
        .on_conflict_do_nothing(index_elements=["dedupe_key"], index_where=text("status = 'queued'"))
    )
    session.execute(text("SELECT pg_notify(:c, :k)"), {"c": CHANNEL, "k": "search.sync"})


def _before_flush(session: Session, _ctx, _instances) -> None:
    """A label or a column carries data into its tasks' documents (label names, the status): note those tasks
    now, while a deleted label's task links still exist."""
    if session.info.get(SKIP):
        return
    labels = [o.id for o in (*session.dirty, *session.deleted) if isinstance(o, Label)]
    columns = [o.id for o in session.dirty if isinstance(o, BoardColumn)]
    if not (labels or columns):
        return
    dirty: set = session.info.setdefault(DIRTY, set())
    if labels:
        rows = session.execute(select(task_labels.c.task_id).where(task_labels.c.label_id.in_(labels)))
        dirty.update(("task", str(t)) for (t,) in rows)
    if columns:
        rows = session.execute(select(Task.id).where(Task.column_id.in_(columns)))
        dirty.update(("task", str(t)) for (t,) in rows)


def _after_soft_rollback(session: Session, previous_transaction) -> None:
    # a rolled-back savepoint keeps the outer transaction's changes, and what they need indexed (re-noting is
    # harmless: a sync rebuilds from the database)
    if previous_transaction.nested:
        return
    session.info.pop(DIRTY, None)
    session.info.pop(PURGE, None)


def install() -> None:
    """Register the hooks once, for every session (the API's and the worker's)."""
    if event.contains(Session, "after_flush", _after_flush):
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "before_commit", _before_commit)
    event.listen(Session, "after_soft_rollback", _after_soft_rollback)
