import itertools

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserStatus
from app.core.security import hash_password

_seq = itertools.count(1)
DEFAULT_PASSWORD = "correct-horse-1"


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
        password_hash=hash_password(password) if password else None,
        **kw,
    )
    db.add(user)
    await db.commit()
    return user


async def login(client, user: User, password: str = DEFAULT_PASSWORD):
    r = await client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert r.status_code == 200, r.text
    return r
