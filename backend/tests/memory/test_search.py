import uuid

from sqlalchemy import delete

from app.memory import entities
from app.memory.extract import embed_texts
from app.memory.models import ConclusionStatus, MemConclusion, ScopeKind
from app.memory.search import search_conclusions
from app.teams.models import TeamMember
from tests.factories import make_project, make_team, make_user


async def _add(db, text, *, scope=(ScopeKind.org, None), status=ConclusionStatus.active, pinned=False):
    org = await entities.org_entity(db)
    model, (vec,) = await embed_texts(db, [text])
    kind, ref = scope
    row = MemConclusion(
        entity_id=org.id, text=text, kind="observed", status=status, pinned=pinned, scope_kind=kind,
        scope_team_id=ref if kind == ScopeKind.team else None,
        scope_project_id=ref if kind == ScopeKind.project else None, embedding=vec, embedding_model=model,
    )
    db.add(row)
    await db.commit()
    return row


async def _world(client, db):
    member = await make_user(db)
    project, _manager, team = await make_project(client, db, "PAY", member)
    outsider = await make_user(db)
    other = await make_team(db, outsider)
    return member, uuid.UUID(project["id"]), team, outsider, other


async def _texts(db, user, q, **kw):
    return [r.text for r in await search_conclusions(db, user, q, **kw)]


async def test_search_respects_scopes_now(client, db):
    member, pid, _team, outsider, _other = await _world(client, db)
    await _add(db, "Payments webhooks retry three times", scope=(ScopeKind.project, pid))
    await _add(db, "Webhooks use HMAC everywhere")
    assert sorted(await _texts(db, member, "webhooks")) == [
        "Payments webhooks retry three times", "Webhooks use HMAC everywhere"
    ]
    assert await _texts(db, outsider, "webhooks") == ["Webhooks use HMAC everywhere"]
    await db.execute(delete(TeamMember).where(TeamMember.user_id == member.id))
    await db.commit()
    assert await _texts(db, member, "webhooks") == ["Webhooks use HMAC everywhere"]


async def test_search_excludes_deleted_and_superseded(client, db):
    member, *_ = await _world(client, db)
    await _add(db, "Deploys happen on Tuesdays", status=ConclusionStatus.deleted)
    await _add(db, "Deploys happen on Wednesdays", status=ConclusionStatus.superseded)
    await _add(db, "Deploys happen on Thursdays")
    assert await _texts(db, member, "deploys") == ["Deploys happen on Thursdays"]


async def test_pinned_ranks_first_among_equals(client, db):
    member, *_ = await _world(client, db)
    await _add(db, "Releases ship weekly")
    await _add(db, "Releases ship weekly too", pinned=True)
    assert (await _texts(db, member, "releases weekly"))[0] == "Releases ship weekly too"


async def test_project_filter_includes_org_and_team_scopes(client, db):
    member, pid, team, _outsider, _other = await _world(client, db)
    admin_like = member
    await _add(db, "Billing uses Stripe", scope=(ScopeKind.project, pid))
    await _add(db, "Billing team owns invoices", scope=(ScopeKind.team, team.id))
    await _add(db, "Billing policy is global")
    project_b, _, _team_b = await make_project(client, db, "OPS", member)
    await _add(db, "Billing in ops is manual", scope=(ScopeKind.project, uuid.UUID(project_b["id"])))
    got = sorted(await _texts(db, admin_like, "billing", project_id=pid))
    assert got == ["Billing policy is global", "Billing team owns invoices", "Billing uses Stripe"]


async def test_unrelated_query_returns_nothing(client, db):
    member, *_ = await _world(client, db)
    await _add(db, "Holiday calendar closes offices on Mondays")
    assert await _texts(db, member, "zebra") == []
    assert await _texts(db, member, "the a of") == []
