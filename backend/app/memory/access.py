"""Who may read and edit memory (MEM-7, §5 permissions). Scopes are read at request time, never cached.

Readable: the org scope, the caller's teams, the projects they can access; admins read everything.
Editable (correct, delete, pin): admins anything; managers anything they can read; members the project and
team scopes they can read; viewers nothing.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, or_, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.memory.models import ScopeKind
from app.projects.access import accessible_project_ids
from app.teams.service import user_team_ids

Scope = tuple[ScopeKind, uuid.UUID | None]


@dataclass
class ReadableScopes:
    all: bool = False
    team_ids: set[uuid.UUID] = field(default_factory=set)
    project_ids: set[uuid.UUID] = field(default_factory=set)

    def contains(self, scope: Scope) -> bool:
        kind, ref = as_scope(*scope)
        if self.all or kind == ScopeKind.org:
            return True
        if kind == ScopeKind.team:
            return ref in self.team_ids
        return ref in self.project_ids

    def clause(self, model):
        """A filter for any model with scope columns (ScopeMixin)."""
        if self.all:
            return true()
        return or_(
            model.scope_kind == ScopeKind.org,
            and_(model.scope_kind == ScopeKind.team, model.scope_team_id.in_(self.team_ids)),
            and_(model.scope_kind == ScopeKind.project, model.scope_project_id.in_(self.project_ids)),
        )


async def readable_scopes(db: AsyncSession, user: User) -> ReadableScopes:
    if user.role == Role.admin:
        return ReadableScopes(all=True)
    return ReadableScopes(
        team_ids=await user_team_ids(db, user.id),
        project_ids=await accessible_project_ids(db, user) or set(),
    )


def as_scope(kind: ScopeKind | str, ref: uuid.UUID | str | None) -> Scope:
    return ScopeKind(kind), uuid.UUID(str(ref)) if ref else None


async def can_read_scope(db: AsyncSession, user: User, scope: Scope) -> bool:
    return (await readable_scopes(db, user)).contains(scope)


async def can_edit_scope(db: AsyncSession, user: User, scope: Scope) -> bool:
    if user.role == Role.viewer:
        return False
    if user.role == Role.admin:
        return True
    if not await can_read_scope(db, user, scope):
        return False
    return user.role == Role.manager or scope[0] != ScopeKind.org
