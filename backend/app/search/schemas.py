from datetime import datetime

from pydantic import BaseModel


class Hit(BaseModel):
    kind: str
    id: str
    title: str  # may carry highlight markers  … ; render as text
    key: str
    url: str | None
    snippet: str
    project_key: str | None
    status: str | None
    updated_at: int
    card: dict | None = None


class QuickGroup(BaseModel):
    kind: str
    hits: list[Hit]


class QuickOut(BaseModel):
    groups: list[QuickGroup]
    total: int


class ProjectFacet(BaseModel):
    id: str
    key: str
    count: int


class AssigneeFacet(BaseModel):
    id: str  # user:<uuid> | agent:<uuid>
    name: str
    count: int


class Facets(BaseModel):
    kind: dict[str, int]
    project: list[ProjectFacet]
    status: dict[str, int]
    assignee: list[AssigneeFacet]
    type: dict[str, int]
    label: dict[str, int]


class SearchOut(BaseModel):
    hits: list[Hit]
    total: int
    facets: Facets
    meaning: list[Hit] | None
    meaning_available: bool


class SearchAdminOut(BaseModel):
    available: bool
    documents: int | None
    last_rebuild_at: datetime | None
