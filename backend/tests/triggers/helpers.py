import uuid

from app.triggers.models import Trigger


async def make_trigger(db, w, event: str, config: dict | None = None, **kw) -> Trigger:
    """A trigger of PAY owned by the world's manager, committed."""
    trigger = Trigger(
        project_id=uuid.UUID(w.project["id"]), name=kw.pop("name", f"On {event}"), event=event,
        config=config if config is not None else {}, prompt=kw.pop("prompt", "Look at it."),
        owner_id=w.manager.id, created_by=w.manager.id, **kw,
    )
    db.add(trigger)
    await db.commit()
    return trigger
