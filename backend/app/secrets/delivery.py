"""The secrets a run gets: its agent owner's own, plus its project's (the project's win on a name). They travel in the
run's start to a runner with secrets/1; the prompt names them, never their values."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import Question
from app.agent_runs.models import AgentRun, RunPolicy
from app.agents.models import Agent
from app.audit import service as audit
from app.core.crypto import decrypt
from app.kb.models import KbSpace, SpaceKind
from app.kb_drafts.models import KbDraft
from app.runner.protocol import RunSecret
from app.runner.registry import SECRETS_CAPABILITY, RunnerConn
from app.secrets.models import Secret
from app.tasks.models import Task

HEADING = "## Secrets you can use"
WORKSPACE_TEXT = (
    "These are set as environment variables. Use them by name — `$NAME` (bash), `$env:NAME` (PowerShell), "
    "`%NAME%` (cmd) — in commands and configuration. Never print, echo, log, commit or write their values to files."
)
READ_ONLY_TEXT = (
    "These are set as environment variables for the tools in your own configuration. Commands in this read-only "
    "session cannot use them. Never print, log or write their values."
)


async def _project_id(db: AsyncSession, run: AgentRun):
    if run.task_id is not None:
        return await db.scalar(select(Task.project_id).where(Task.id == run.task_id))
    if run.question_id is not None:  # an answering run reads the asked project's code
        return await db.scalar(select(Question.target_project_id).where(Question.id == run.question_id))
    if run.cron_run_id is not None:
        from app.crons.models import Cron, CronRun  # local: crons imports agent_runs

        return await db.scalar(select(Cron.project_id).join(CronRun, CronRun.cron_id == Cron.id)
                               .where(CronRun.id == run.cron_run_id))
    if run.draft_id is not None:  # a team's or the organization's draft has no project
        space = await db.scalar(
            select(KbSpace).join(KbDraft, KbDraft.space_id == KbSpace.id).where(KbDraft.id == run.draft_id)
        )
        return space.project_id if space is not None and space.kind == SpaceKind.project else None
    return None


async def secrets_for_run(db: AsyncSession, run: AgentRun) -> list[tuple[str, str, str]]:
    """(name, description, value) by name: the agent's owner's personal secrets (never the requester's), then the
    run's project's, which win on a name."""
    owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id))
    project_id = await _project_id(db, run)
    found: dict[str, Secret] = {}
    for s in (await db.execute(select(Secret).where(Secret.user_id == owner_id))).scalars():
        found[s.name] = s
    if project_id is not None:
        for s in (await db.execute(select(Secret).where(Secret.project_id == project_id))).scalars():
            found[s.name] = s
    return [(name, s.description, decrypt(s.value_enc)) for name, s in sorted(found.items())]


async def values_for_run(db: AsyncSession, run: AgentRun) -> dict[str, str]:
    return {name: value for name, _, value in await secrets_for_run(db, run)}


def prompt_section(secrets: list[tuple[str, str, str]], policy: RunPolicy | str) -> str:
    if not secrets:
        return ""
    text = READ_ONLY_TEXT if RunPolicy(policy) == RunPolicy.read_only else WORKSPACE_TEXT
    lines = [f"- {name} — {description}" for name, description, _ in secrets]
    return "\n".join([HEADING, "", text, "", *lines])


async def add_to_start(
    db: AsyncSession, run: AgentRun, conn: RunnerConn, prompt: str, v2: dict
) -> tuple[str, list[str]]:
    """Puts the run's secrets into its run_start fields (`v2`) and their names into the prompt (and the resumed
    session's prompt), for a runner with secrets/1. Returns the prompt and the names handed over."""
    if SECRETS_CAPABILITY not in conn.capabilities:
        return prompt, []
    secrets = await secrets_for_run(db, run)
    if not secrets:
        return prompt, []
    v2["secrets"] = [RunSecret(name=name, value=value) for name, _, value in secrets]
    section = prompt_section(secrets, run.policy)
    if v2.get("resume_prompt"):
        v2["resume_prompt"] = f"{v2['resume_prompt']}\n\n{section}"
    return f"{prompt}\n\n{section}", [name for name, _, _ in secrets]


async def audit_delivery(db: AsyncSession, run: AgentRun, names: list[str]) -> None:
    if names:
        await audit.record(db, "secret.delivered", actor_id=run.requested_by, target_type="agent_run",
                           target_id=run.id, data={"run_id": str(run.id), "names": names})
