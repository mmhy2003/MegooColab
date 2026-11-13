"""A model and effort for each workflow stage, set on the agent (spec 2026-11-13-stage-models-design). Each run of a
stage's roles starts on the stage's choice; a stage without one, on the agent's own."""

from app.agents.models import Agent
from app.runner.protocol import RunModelChoice
from app.workflow.models import RunRole

# the stages, grouped by the kind of work: a writing stage and a reviewing stage can differ
STAGE_ROWS: dict[str, frozenset[RunRole]] = {
    "design": frozenset({RunRole.brainstorm}),
    "plan": frozenset({RunRole.plan}),
    "build": frozenset({RunRole.implement, RunRole.step_fix, RunRole.final_fix, RunRole.pr_fix}),
    "review": frozenset({RunRole.step_review, RunRole.final_review, RunRole.pr_review}),
    "finish": frozenset({RunRole.finish}),
}


def row_for(role: RunRole) -> str | None:
    """The stage a role belongs to; None for a freestyle turn, which always runs on the agent's own."""
    return next((row for row, roles in STAGE_ROWS.items() if role in roles), None)


def run_model(agent: Agent, role: RunRole) -> RunModelChoice | None:
    """The model and effort a run of this role starts on, sent as run_start.model_choice: None when the agent has
    no stage of its own (the run goes as before) or the role has no stage. "" is the program's starting model / the
    model's default effort, so a continued session goes back to them."""
    rows = agent.stage_models or {}
    row = row_for(role)
    if not rows or row is None:
        return None
    mine = rows.get(row, {})
    if mine.get("model"):  # its own model, with its own effort or that model's default
        return RunModelChoice(model=mine["model"], effort=mine.get("effort") or "")
    return RunModelChoice(model=agent.model or "", effort=mine.get("effort") or agent.effort or "")


def overriding_roles(agent: Agent) -> set[RunRole]:
    """The roles whose stage sets a model or an effort: their runs wait for a runner with stagemodel/1."""
    rows = agent.stage_models or {}
    return {role for row, roles in STAGE_ROWS.items() if rows.get(row) for role in roles}
