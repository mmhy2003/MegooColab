"""What a freestyle turn is told (freestyle chats, Task 3): a fresh session gets the conversation so far, a resumed
one only its new messages, and the person's messages come in freestyle's own words."""

import json
import uuid
from datetime import timedelta

from app.agent_runs.models import AgentRun
from app.agent_runs.service import dispatch_pending
from app.core.db import SessionLocal
from app.runner.registry import registry
from app.tasks.models import Comment, Delivery, Task, TaskEvent
from app.workflow import engine, freestyle, instructions
from tests.agent_runs.test_dispatch import _fake_conn, _FakeSocket
from tests.workflow.test_freestyle_engine import _end, _freestyle, _waiting_comment
from tests.workflow.test_instructions_dispatch import _dispatch, _message, _world

REPLY = "Created release/2026.11.06.208"
WORKFLOW_WORDS = "approved design or plan"


async def _delivered(task_id, w, body, *, at, run=None):
    """A message the agent already got (given at the start of `run`)."""
    async with SessionLocal() as s:
        s.add(Comment(task_id=task_id, author_user_id=w.owner.id, body_md=body, to_agent_id=uuid.UUID(w.agent["id"]),
                      delivery=Delivery.given_at_start, delivery_run_id=run.id if run else None, created_at=at))
        await s.commit()


async def _second_turn(task_id, owner_id, session=None) -> AgentRun:
    """Queue turn 2, on a stored session (`session`) or none."""
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, task_id)
        wf.sessions.clear()
        if session:
            wf.sessions["freestyle"] = session
        run = await freestyle.queue_turn(s, wf, await s.get(Task, task_id), requested_by=owner_id)
        await s.commit()
        return run


async def _two_turns(client, db, session=None):
    """Turn 1 got "first ask" and replied REPLY; then "push it" waits, and turn 2 is queued."""
    w, task_id, run = await _freestyle(client, db)
    await _delivered(task_id, w, "first ask", at=run.created_at - timedelta(seconds=1), run=run)
    await _end(run.id, "completed", REPLY)
    await _waiting_comment(task_id, w, "push it", after=run)
    turn = await _second_turn(task_id, w.owner.id, session)
    return w, task_id, turn


async def test_fresh_freestyle_prompt_has_the_conversation_so_far(client, db):
    w, task_id, turn = await _two_turns(client, db)
    assert turn.resume_session_ref is None
    start = await _dispatch(w.owner, w.agent)
    assert start["run_id"] == str(turn.id)
    prompt = start["prompt"]
    i = prompt.index("## Conversation so far")
    assert i < prompt.index("> first ask") < prompt.index(REPLY) < prompt.index("> push it")
    assert prompt.index("## Task") < i < prompt.index("## Thread")
    # the agent's reply is its own text, not the person's: wrapped as untrusted, under who said it and when
    assert '[reply by laptop-claude at ' in prompt
    assert f'<untrusted source="agent_reply">\n{REPLY}\n</untrusted>' in prompt
    assert "## Instructions from people on this task" not in prompt


async def test_resumed_freestyle_turn_is_not_resent_earlier_messages(client, db):
    w, task_id, turn = await _two_turns(client, db, session="s1")
    assert turn.resume_session_ref == "s1"
    start = await _dispatch(w.owner, w.agent)
    assert start["resume_session_id"] == "s1"
    assert "> push it" in start["resume_prompt"]
    assert "## New instructions\n" + instructions.FREESTYLE_RULE in start["resume_prompt"]
    assert "first ask" not in start["resume_prompt"] and REPLY not in start["resume_prompt"]


async def test_freestyle_messages_use_freestyle_wording(client, db):
    w, task_id, _ = await _two_turns(client, db)
    start = await _dispatch(w.owner, w.agent)
    assert "## New instructions\n" + instructions.FREESTYLE_RULE in start["prompt"]
    assert "The person you are working with sent you this. Do what it asks." in start["prompt"]
    assert WORKFLOW_WORDS not in start["prompt"]


async def _key(task_id) -> str:
    async with SessionLocal() as s:
        return f"PAY-{(await s.get(Task, task_id)).number}"


async def test_freestyle_steer_uses_freestyle_wording(client, db):
    w, task_id, run = await _freestyle(client, db)
    sock = _FakeSocket()
    conn = await _fake_conn(w.owner, w.agent, sock)
    conn.capabilities.add("steer/1")
    try:
        async with SessionLocal() as s:
            await dispatch_pending(s, w.owner.id)  # the turn is running
            await s.commit()
        await _message(client, await _key(task_id), "and tag it")  # steered into it straight away
    finally:
        registry._conns.pop(w.owner.id, None)
    [steer] = [m for m in map(json.loads, sock.sent) if m["type"] == "run_steer"]
    assert steer["run_id"] == str(run.id)
    assert steer["text"].startswith(instructions.FREESTYLE_STEER_PREFIX) and "> and tag it" in steer["text"]
    assert WORKFLOW_WORDS not in steer["text"]


async def test_workflow_messages_keep_their_wording(client, db):
    me, agent, run_id, key = await _world(client, db, workflow_role="brainstorm", stage="brainstorm")
    await _message(client, key, "Log retries")
    start = await _dispatch(me, agent)
    assert "## New instructions\n" + instructions.RULE in start["prompt"]
    assert WORKFLOW_WORDS in start["prompt"]
    assert instructions.FREESTYLE_RULE not in start["prompt"]


async def test_conversation_keeps_the_newest_within_its_budget(client, db):
    w, task_id, run = await _freestyle(client, db)
    for i in range(3):
        await _delivered(task_id, w, f"M{i} " + "x" * 5_000, at=run.created_at + timedelta(minutes=i))
    async with SessionLocal() as s:
        text = await freestyle.conversation_so_far(s, await s.get(Task, task_id))
    assert text.startswith("## Conversation so far\n")
    assert len(text) <= freestyle.CONVERSATION_CHARS
    assert "> M0 " not in text and "> M1 " in text and "> M2 " in text
    assert "(1 older messages omitted to fit.)" in text


async def test_no_conversation_yet_no_section(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _end(run.id, "completed", "  ")  # a blank reply says nothing
    async with SessionLocal() as s:
        assert await freestyle.conversation_so_far(s, await s.get(Task, task_id)) is None


async def _events(task_id, run, *events):
    """The run's streamed updates, a second apart: (kind, data) pairs."""
    async with SessionLocal() as s:
        for i, (kind, data) in enumerate(events):
            s.add(TaskEvent(task_id=task_id, kind=kind, data={**data, "run_id": str(run.id)},
                            created_at=run.created_at + timedelta(seconds=i + 1)))
        await s.commit()


async def _conversation(task_id) -> str | None:
    async with SessionLocal() as s:
        return await freestyle.conversation_so_far(s, await s.get(Task, task_id))


async def test_reply_is_the_turns_last_message_not_its_summary(client, db):
    """The runner's summary is only the last flushed chunk: the reply is the last message the agent streamed, the
    chunks after its last tool use joined."""
    w, task_id, run = await _freestyle(client, db)
    await _events(
        task_id, run,
        ("agent_message", {"text": "Looking at the version file"}),
        ("agent_tool", {"title": "bump"}),
        ("agent_message", {"text": "Created release/"}),
        ("agent_message", {"text": "2026.11.06.208 and bumped VERSION"}),
    )
    await _end(run.id, "completed", "bumped VERSION")
    text = await _conversation(task_id)
    assert '<untrusted source="agent_reply">\nCreated release/2026.11.06.208 and bumped VERSION\n</untrusted>' in text
    assert "Looking at the version file" not in text


async def test_long_reply_keeps_its_newest_characters(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _events(
        task_id, run, ("agent_message", {"text": "START " + "x" * 5_000}), ("agent_message", {"text": " END"})
    )
    await _end(run.id, "completed", " END")
    text = await _conversation(task_id)
    assert "START" not in text and "x END\n</untrusted>" in text
    opening = '<untrusted source="agent_reply">\n'
    reply = text[text.index(opening) + len(opening):text.index("\n</untrusted>")]
    assert len(reply) == freestyle.REPLY_CHARS


async def test_reply_falls_back_to_the_summary_without_messages(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _events(task_id, run, ("agent_tool", {"title": "bump"}))
    await _end(run.id, "completed", "Done: bumped VERSION")
    assert '<untrusted source="agent_reply">\nDone: bumped VERSION\n</untrusted>' in await _conversation(task_id)
