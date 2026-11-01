"""A project PAY with a member who owns an agent bound to it, another member, and the project's manager."""

from dataclasses import dataclass

from app.auth.models import Role, User
from app.workflow import methodology
from tests.factories import login, make_project, make_user


@dataclass
class World:
    owner: User
    other: User
    manager: User
    agent: dict


async def world(client, db, *, viewer: User | None = None) -> World:
    """Leaves `client` logged in as the agent's owner."""
    owner = await make_user(db, name="Owen Owner")
    other = await make_user(db, name="Mia Member")
    extra = (viewer,) if viewer else ()
    _, manager, _ = await make_project(client, db, "PAY", owner, other, *extra)
    await methodology.seed_defaults(db)
    await db.commit()
    await login(client, owner)
    agent = (await client.post("/api/agents", json={"program": "claude_code", "name": "laptop-claude"})).json()
    r = await client.put(
        f"/api/agents/{agent['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/repo"}]}
    )
    assert r.status_code == 200, r.text
    return World(owner, other, manager, agent)


async def start(client, message="Fix the empty email crash\nIt returns a 500.", **extra) -> dict:
    r = await client.post("/api/chats", json={"project_key": "PAY", "message": message, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def viewer_user(db) -> User:
    return await make_user(db, role=Role.viewer, name="Vic Viewer")
