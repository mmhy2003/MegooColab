"""A draft's agent turns. Each request is a read-only AgentRun targeting the draft (beside task and question runs):
queued and dispatched like any other run, resuming the agent's session of the draft's earlier turns. The agent reads
the draft and submits its new text through the kb_draft MCP tools; the submission becomes the turn's marks."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunPolicy, RunStatus
from app.agent_runs.tokens import issue_run_token
from app.agents.models import Agent, AgentBinding
from app.agents.service import owner_can_access
from app.auth.models import User
from app.core.config import get_settings
from app.kb.models import KbDocument, KbSpace, SpaceKind
from app.kb import service as kb
from app.kb_drafts import blocks, prompts
from app.kb_drafts.models import KbDraft, KbDraftMessage
from app.kb_drafts.service import (
    active_run,
    add_message,
    check_agent,
    refuse_while_writing,
    settle,
    touch,
)
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project
from app.runner.protocol import DraftDone, McpAccess, RunCancel, RunDraft, RunTask
from app.runner.registry import DRAFTS_CAPABILITY, RunnerClosed, registry


class NotSupported(Exception):
    """The run cannot be started: the draft or its agent's binding is gone."""


def draft_link(draft_id: uuid.UUID) -> str:
    return f"/kb/drafts/{draft_id}"


async def enqueue_turn(
    db: AsyncSession, draft: KbDraft, *, request: str, target: dict | None, newer: dict | None = None
) -> AgentRun:
    agent = await db.get(Agent, draft.agent_id) if draft.agent_id else None
    if agent is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")
    prompt, resume_prompt, version = await prompts.turn_prompt(db, draft, request, target, newer)
    run = AgentRun(
        id=uuid.uuid4(), draft_id=draft.id, agent_id=agent.id, requested_by=draft.user_id,
        policy=RunPolicy.read_only, prompt=prompt,
        resume_session_ref=draft.session_ref, resume_prompt=resume_prompt if draft.session_ref else None,
        methodology_version_id=version.id,
        draft_request={"request": request, "target": target, "newer": newer, "submitted": False},
    )
    db.add(run)
    await db.flush()
    from app.workflow import engine  # local: the engine imports agent_runs, which calls into this module

    db.info.setdefault(engine._DISPATCH_KEY, set()).add(agent.owner_id)  # sent after the caller commits
    await notifications.read_by_acting(db, draft.user_id, link=draft_link(draft.id))
    return run


async def request_turn(db: AsyncSession, user: User, draft: KbDraft, text: str, target: dict | None) -> AgentRun:
    """The person's request: the open marks are kept, and the agent gets a new turn."""
    await check_agent(db, user, await db.get(KbSpace, draft.space_id), draft.agent_id)
    await refuse_while_writing(db, draft)
    settle(draft)
    add_message(db, draft, "person", text, target=target)
    run = await enqueue_turn(db, draft, request=text, target=target)
    await touch(db, draft)
    return run


async def stop(db: AsyncSession, user: User, draft: KbDraft) -> None:
    from app.agent_runs.service import cancel_run  # local: agent_runs calls into this module

    run = await active_run(db, draft.id)
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "run_not_active")
    await cancel_run(db, user, run)


async def apply_submission(db: AsyncSession, run: AgentRun, body_md: str, reply: str, title: str | None) -> int:
    """The agent's work of this turn: its whole new text becomes the turn's marks against the draft as it is now, its
    reply goes into the conversation. Once per run; nothing once the draft is gone. Returns the number of changes."""
    draft = (
        await db.execute(
            select(KbDraft).where(KbDraft.id == run.draft_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "draft_gone")
    run = (
        await db.execute(
            select(AgentRun).where(AgentRun.id == run.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one()
    asked = run.draft_request or {}
    if asked.get("submitted"):
        raise HTTPException(status.HTTP_409_CONFLICT, "already_submitted")
    kb.check_body(body_md)
    turn = blocks.new_turn(asked.get("request") or "", draft.body_md, body_md)
    if turn is not None:
        draft.turn = turn
        draft.body_md = blocks.compose(turn)
    if title:
        draft.title = title
    run.draft_request = {**asked, "submitted": True}
    add_message(db, draft, "agent", reply, run_id=run.id)
    await touch(db, draft)
    return blocks.open_count(turn)


async def bring_in(db: AsyncSession, user: User, draft: KbDraft) -> AgentRun:
    """Someone saved the document meanwhile: the agent brings their version into the draft, which is then based on
    it (a save no longer conflicts with it)."""
    if draft.document_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_a_document")
    await check_agent(db, user, await db.get(KbSpace, draft.space_id), draft.agent_id)
    await refuse_while_writing(db, draft)
    doc = await db.get(KbDocument, draft.document_id)
    newer = {"revision": doc.latest_revision, "body_md": doc.body_md}
    draft.base_revision = doc.latest_revision
    settle(draft)
    text = (f"Someone saved a newer version (rev {doc.latest_revision}). Bring their changes into the draft and keep "
            "ours where they don't conflict.")
    add_message(db, draft, "person", text)
    run = await enqueue_turn(db, draft, request=text, target=None, newer=newer)
    await touch(db, draft)
    return run


async def stop_runs_of(db: AsyncSession, draft_ids: list[uuid.UUID]) -> None:
    """These drafts are about to be deleted, and their runs with them: a running agent is stopped (its later
    run_finished, for a run that no longer exists, is ignored); a queued run simply goes."""
    runs = (
        await db.execute(
            select(AgentRun).where(AgentRun.draft_id.in_(draft_ids), AgentRun.status == RunStatus.running)
            .with_for_update()
        )
    ).scalars().all()
    for run in runs:
        conn = registry.conn_for_run(run.id)
        if conn is not None:
            try:
                await conn.send(RunCancel(run_id=run.id))
            except RunnerClosed:
                pass


async def send_draft_done(agent_id: uuid.UUID | None, draft_id: uuid.UUID) -> None:
    """Best effort: the agent's runner removes the draft's folder. A runner that is away removes it within 30 days."""
    conn = registry.conn_for_agent(agent_id) if agent_id else None
    if conn is None or DRAFTS_CAPABILITY not in conn.capabilities:
        return
    try:
        await conn.send(DraftDone(agent_id=agent_id, draft_id=draft_id))
    except RunnerClosed:
        pass


async def drafts_of_document(db: AsyncSession, doc_id: uuid.UUID) -> list[tuple[uuid.UUID | None, uuid.UUID]]:
    """Before a document is deleted (its drafts go with it): their agents are stopped. Returns (agent_id, draft_id) of
    each draft, for send_draft_done once the delete is committed."""
    rows = (await db.execute(select(KbDraft.agent_id, KbDraft.id).where(KbDraft.document_id == doc_id))).all()
    await stop_runs_of(db, [d for _, d in rows])
    return [(a, d) for a, d in rows]


async def start_fields(db: AsyncSession, run: AgentRun) -> tuple[RunTask, str, dict]:
    """(RunTask, local_path, v2 fields) for a draft run's run_start: a synthetic task key `KBD-<draft>` that the runner
    keys the draft's folder on, the project's repository for a project draft (none otherwise), the run's MCP token,
    and the session to resume."""
    draft = await db.get(KbDraft, run.draft_id)
    if draft is None:
        raise NotSupported("draft_gone")
    space = await db.get(KbSpace, draft.space_id)
    project_key, local_path = "", ""
    if space.kind == SpaceKind.project:
        project = await db.get(Project, space.project_id)
        local_path = await db.scalar(
            select(AgentBinding.local_path)
            .join(Agent, Agent.id == AgentBinding.agent_id)
            .where(AgentBinding.agent_id == run.agent_id, AgentBinding.project_id == project.id,
                   owner_can_access(project.id))
        )
        if local_path is None:
            raise NotSupported("agent_not_bound")
        project_key = project.key
    task = RunTask(key=f"KBD-{draft.id.hex[:12]}", title=draft.title or "Draft", description_md="",
                   project_key=project_key)
    fields = {
        "role": "kb_draft",
        "mcp": McpAccess(url=get_settings().public_url.rstrip("/") + "/api/mcp", token=issue_run_token(run)),
        "resume_session_id": run.resume_session_ref,
        "resume_prompt": run.resume_prompt,
        "draft": RunDraft(id=draft.id),
    }
    return task, local_path, fields


async def on_run_finished(db: AsyncSession, run: AgentRun) -> None:
    """A draft turn ended: keep the agent's session for the next one, say in the conversation when it changed nothing,
    and tell the person when it did."""
    draft = await db.get(KbDraft, run.draft_id)
    if draft is None:
        return
    if run.session_ref:
        draft.session_ref = run.session_ref
    agent = await db.get(Agent, run.agent_id)
    name = agent.name if agent else "The agent"
    submitted = bool((run.draft_request or {}).get("submitted"))
    if submitted:
        reply = await db.scalar(
            select(KbDraftMessage.text).where(KbDraftMessage.run_id == run.id, KbDraftMessage.author == "agent")
        )
        await notifications.notify(
            db, [draft.user_id], Kind.needs_you, title=f"{name} updated your draft '{draft.title or 'Untitled'}'",
            body=(reply or "").strip().split("\n")[0], link=draft_link(draft.id),
        )
    elif run.status == RunStatus.cancelled:
        add_message(db, draft, "system", f"{name} stopped before changing the draft.", run_id=run.id)
    elif run.status == RunStatus.failed:
        add_message(db, draft, "system", f"{name} couldn't finish ({run.reason or 'agent_error'}).", run_id=run.id)
    else:
        add_message(db, draft, "system", f"{name} finished without changing the draft.", run_id=run.id)
    await touch(db, draft)
