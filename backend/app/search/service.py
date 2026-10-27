"""Searching (Plan 9): every query is restricted to the reader tokens of the person searching, worked out from the
database at search time, so results, totals, facet counts and snippets only ever include what they can open.

Filter values never reach Meilisearch unchecked: kinds, statuses, types and the updated window come from fixed
lists, ids must parse as UUIDs, and the remaining strings (labels) are quoted with `"` and `\\` escaped.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.ai import client as ai
from app.auth.models import Role, User
from app.kb import access as kb_access
from app.kb import search as kb_search
from app.projects.access import accessible_project_ids
from app.projects.models import Project
from app.search import client
from app.search.documents import KINDS
from app.search.schemas import (
    AssigneeFacet,
    Facets,
    GlobalSearchOut,
    Hit,
    ProjectFacet,
    QuickGroup,
    QuickOut,
)
from app.tasks.models import TaskType

PRE, POST = "", ""
QUICK_PER_KIND = 5
PAGE = 20
MAX_Q = 200
MAX_VALUES = 20
MAX_LABEL = 50
STATUSES = ("before", "working", "review", "done")
UPDATED = {"7d": 7, "30d": 30, "365d": 365}
SORTS = ("relevance", "newest")
FACETS = ["kind", "project_id", "status", "assignee", "type", "labels"]
FACET_FILTERS = [("kind", "kinds"), ("project_id", "projects"), ("status", "statuses"), ("assignee", "assignees"),
                 ("type", "types"), ("labels", "labels")]
SEARCH_PARAMS: dict[str, Any] = {
    "matchingStrategy": "all",
    "attributesToHighlight": ["title", "key", "body", "comments"],
    "attributesToCrop": ["body", "comments"],
    "cropLength": 24,
    "highlightPreTag": PRE,
    "highlightPostTag": POST,
}


def _invalid() -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_filter")


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Filters:
    kinds: list[str] = field(default_factory=list)
    projects: list[uuid.UUID] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    updated: str | None = None


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise _invalid() from None


def parse_filters(
    kind: list[str], project: list[str], status_: list[str], assignee: list[str], type_: list[str],
    label: list[str], updated: str | None,
) -> Filters:
    """Validate every filter value (422 invalid_filter); nothing unchecked reaches the filter expression."""
    if any(len(v) > MAX_VALUES for v in (kind, project, status_, assignee, type_, label)):
        raise _invalid()
    if any(k not in KINDS for k in kind) or any(s not in STATUSES for s in status_):
        raise _invalid()
    if any(t not in {str(x) for x in TaskType} for t in type_):
        raise _invalid()
    if updated is not None and updated not in UPDATED:
        raise _invalid()
    assignees = []
    for a in assignee:
        prefix, _, rest = a.partition(":")
        if prefix not in ("user", "agent"):
            raise _invalid()
        assignees.append(f"{prefix}:{_uuid(rest)}")
    if any(not lb or len(lb) > MAX_LABEL for lb in label):
        raise _invalid()
    return Filters(
        kinds=list(dict.fromkeys(kind)), projects=[_uuid(p) for p in project], statuses=list(dict.fromkeys(status_)),
        assignees=assignees, types=list(dict.fromkeys(type_)), labels=list(dict.fromkeys(label)), updated=updated,
    )


async def reader_tokens(db: AsyncSession, user: User) -> list[str] | None:
    """The tokens this person may read; None for admins, who can open everything."""
    if user.role == Role.admin:
        return None
    projects = await accessible_project_ids(db, user) or set()
    spaces = await kb_access.readable_space_ids(db, user)
    return ["all", f"user:{user.id}", *(f"project:{p}" for p in sorted(projects, key=str)),
            *(f"space:{s}" for s in sorted(spaces, key=str))]


def _any_of(attr: str, values: list[str]) -> str:
    return f"{attr} IN [{', '.join(_quoted(v) for v in values)}]"


def build_filter(tokens: list[str] | None, f: Filters | None = None, *, now: datetime | None = None) -> list[str]:
    """A Meilisearch filter array (every element must hold)."""
    out: list[str] = []
    if tokens is not None:
        out.append(_any_of("readers", tokens))
    if f is None:
        return out
    if f.kinds:
        out.append(_any_of("kind", f.kinds))
    if f.projects:
        out.append(_any_of("project_id", [str(p) for p in f.projects]))
    if f.statuses:
        out.append(_any_of("status", f.statuses))
    if f.assignees:
        out.append(_any_of("assignee", f.assignees))
    if f.types:
        out.append(_any_of("type", f.types))
    if f.labels:
        out.append(_any_of("labels", f.labels))
    if f.updated:
        since = (now or datetime.now(UTC)) - timedelta(days=UPDATED[f.updated])
        out.append(f"updated_at >= {int(since.timestamp())}")
    return out


def _snippet(formatted: dict) -> str:
    comments = formatted.get("comments") or ""
    body = formatted.get("body") or ""
    if PRE in comments and PRE not in body:
        return comments
    return body or comments


def _hit(raw: dict, readable: set[str] | None) -> Hit:
    formatted = raw.get("_formatted") or raw
    card = raw.get("card")
    if raw.get("kind") == "agent" and card and readable is not None:
        card = {**card, "projects": [p for p in card.get("projects", []) if f"project:{p['id']}" in readable]}
    return Hit(
        kind=raw["kind"], id=raw["id"].split("-", 1)[1], title=formatted.get("title") or raw.get("title") or "",
        key=formatted.get("key") or raw.get("key") or "", url=raw.get("url"), snippet=_snippet(formatted),
        project_key=raw.get("project_key"), status=raw.get("status"), updated_at=raw.get("updated_at") or 0,
        card=card,
    )


async def quick(db: AsyncSession, user: User, q: str) -> QuickOut:
    tokens = await reader_tokens(db, user)
    base = build_filter(tokens)
    index = client.index().uid
    queries = [
        {"indexUid": index, "q": q, **SEARCH_PARAMS, "filter": [*base, _any_of("kind", [k])], "limit": QUICK_PER_KIND}
        for k in KINDS
    ] + [{"indexUid": index, "q": q, "matchingStrategy": "all", "filter": base, "limit": 0}]
    res = await client.call(lambda: client.client().multi_search(queries))
    results = res["results"]
    readable = set(tokens) if tokens is not None else None
    groups = [
        QuickGroup(kind=k, hits=[_hit(h, readable) for h in r["hits"]])
        for k, r in zip(KINDS, results[:-1], strict=True) if r["hits"]
    ]
    return QuickOut(groups=groups, total=int(results[-1].get("estimatedTotalHits") or 0))


async def _facets(db: AsyncSession, dist: dict[str, dict[str, int]]) -> Facets:
    project_counts = dist.get("project_id", {})
    keys = dict(
        (await db.execute(select(Project.id, Project.key).where(Project.id.in_([_uuid(p) for p in project_counts]))))
        .all()
    ) if project_counts else {}
    assignee_counts = dist.get("assignee", {})
    user_ids = [_uuid(a.split(":", 1)[1]) for a in assignee_counts if a.startswith("user:")]
    agent_ids = [_uuid(a.split(":", 1)[1]) for a in assignee_counts if a.startswith("agent:")]
    users = dict((await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    agents = dict((await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))))
                  .all()) if agent_ids else {}

    def assignee_name(token: str) -> str:
        prefix, _, rest = token.partition(":")
        return (users if prefix == "user" else agents).get(uuid.UUID(rest), "Unknown")

    return Facets(
        kind=dist.get("kind", {}),
        project=sorted(
            (ProjectFacet(id=p, key=keys[uuid.UUID(p)], count=n) for p, n in project_counts.items()
             if uuid.UUID(p) in keys),
            key=lambda f: f.key,
        ),
        status=dist.get("status", {}),
        assignee=sorted(
            (AssigneeFacet(id=a, name=assignee_name(a), count=n) for a, n in assignee_counts.items()),
            key=lambda f: f.name.lower(),
        ),
        type=dist.get("type", {}),
        label=dist.get("labels", {}),
    )


async def full(
    db: AsyncSession, user: User, q: str, f: Filters, sort: str = "relevance", offset: int = 0, meaning: bool = False,
) -> GlobalSearchOut:
    tokens = await reader_tokens(db, user)
    index = client.index().uid
    main: dict[str, Any] = {
        "indexUid": index, "q": q, **SEARCH_PARAMS, "filter": build_filter(tokens, f), "limit": PAGE,
        "offset": offset, "facets": FACETS,
    }
    if sort == "newest":
        main["sort"] = ["updated_at:desc"]
    # a chosen group's own counts leave out its own filter, so its other values stay on offer (pick several);
    # every query keeps the readers filter
    chosen = [(attr, name) for attr, name in FACET_FILTERS if getattr(f, name)]
    queries = [main] + [
        {"indexUid": index, "q": q, "matchingStrategy": "all", "limit": 0, "facets": [attr],
         "filter": build_filter(tokens, replace(f, **{name: []}))}
        for attr, name in chosen
    ]
    results = (await client.call(lambda: client.client().multi_search(queries)))["results"]
    res = results[0]
    dist = dict(res.get("facetDistribution") or {})
    for (attr, _), extra in zip(chosen, results[1:], strict=True):
        dist[attr] = (extra.get("facetDistribution") or {}).get(attr, {})
    readable = set(tokens) if tokens is not None else None
    hits = [_hit(h, readable) for h in res["hits"]]
    available = await ai.current_model(db, "embeddings") is not None
    similar = None
    if meaning and available and (not f.kinds or "document" in f.kinds):
        shown = {h.id for h in hits if h.kind == "document"}
        found = await kb_search.search(db, user, q, limit=QUICK_PER_KIND)
        similar = [
            Hit(kind="document", id=str(r["document_id"]), title=r["title"], key="", url=f"/kb/doc/{r['document_id']}",
                snippet=r.get("snippet") or "", project_key=None, status=None, updated_at=0)
            for r in found["results"] if str(r["document_id"]) not in shown
        ]
    return GlobalSearchOut(
        hits=hits, total=int(res.get("estimatedTotalHits") or 0), facets=await _facets(db, dist),
        meaning=similar, meaning_available=available,
    )
