import itertools

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserStatus
from app.core.security import hash_password

_seq = itertools.count(1)
DEFAULT_PASSWORD = "correct-horse-1"
_DEFAULT_HASH = hash_password(DEFAULT_PASSWORD)  # hashing is slow on purpose; do it once


async def make_user(
    db: AsyncSession,
    role: Role = Role.member,
    password: str | None = DEFAULT_PASSWORD,
    status: UserStatus = UserStatus.active,
    **kw,
) -> User:
    n = next(_seq)
    user = User(
        email=kw.pop("email", f"user{n}@example.com").lower(),
        name=kw.pop("name", f"User {n}"),
        role=role,
        status=status,
        password_hash=(_DEFAULT_HASH if password == DEFAULT_PASSWORD else hash_password(password)) if password else None,
        **kw,
    )
    db.add(user)
    await db.commit()
    return user


async def login(client, user: User, password: str = DEFAULT_PASSWORD):
    r = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert r.status_code == 200, r.text
    return r


async def make_team(db: AsyncSession, *members: User, name: str | None = None):
    from app.teams.models import Team, TeamMember

    team = Team(name=name or f"Team {next(_seq)}", description="")
    db.add(team)
    await db.flush()
    for m in members:
        db.add(TeamMember(team_id=team.id, user_id=m.id))
    await db.commit()
    return team


async def make_project(client, db, key: str = "PAY", *members: User):
    """Creates a team (manager + members) and a project through the API; returns (project_json, manager, team)."""
    from app.auth.models import Role

    manager = await make_user(db, role=Role.manager)
    team = await make_team(db, manager, *members)
    await login(client, manager)
    r = await client.post(
        "/api/projects",
        json={"key": key, "name": f"Project {key}", "description": "", "team_ids": [str(team.id)]},
    )
    assert r.status_code == 201, r.text
    return r.json(), manager, team
