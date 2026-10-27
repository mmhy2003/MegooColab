"""Workflow MCP tools: how coding agents talk back to the workflow engine (AGT-31..33, WF-5).

Two kinds of caller:
- A run token (`mgr_`; runner-driven, enforced; `current_run` is set). `key` must be the run's own task
  (wrong_task), and the tool one its role may use (TOOL_ROLES, else not_allowed_in_role). The token resolver
  checked that the run was running when the request arrived; a run can end mid-call, so every tool that changes
  state re-checks it under the workflow lock (run_not_running).
- A personal token (`mgc_`; connect-only, unenforced, AGT-32). Only on a task whose human assignee is the
  caller (not_your_task), never on a runner-driven one (runner_driven). The first stage tool starts the
  connect_only workflow; stages are gated by the connect-only service functions, and no run is ever queued.
  With no review or finish runs, submit_review and report_finish are refused (not_allowed_in_role): approving the
  plan starts Build, complete_step advances step by step, and the last step finishes the workflow.

Errors are tool errors carrying the REST error code. Every text is NUL-stripped and capped by its service
(too_large), and the whole request body by the transport.
"""

from typing import Any

from fastapi import HTTPException, status
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.mcp_server.auth import current_run, live_run, require_run_task, tool_session
from app.projects.models import Project
from app.tasks.models import Task
from app.tasks.service import get_task_for
from app.workflow import (
    build,
    documents,
    engine,
    finish,
    methodology,
    mockups,
    questions,
)
from app.workflow.context import ROLE_KEY
from app.workflow.models import (
    DocKind,
    DocStatus,
    MethodologyVersion,
    Needs,
    RunRole,
    Stage,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowStatus,
)

ASKED = "Question posted. End your turn now; the answer arrives as your next message."

TOOL_ROLES: dict[str, frozenset[RunRole]] = {
    "get_workflow": frozenset(RunRole),
    "get_document": frozenset(RunRole),
    # a reviewer never asks: it judges what is there
    "ask_human": frozenset({
        RunRole.brainstorm, RunRole.plan, RunRole.implement, RunRole.step_fix, RunRole.final_fix, RunRole.finish,
    }),
    "submit_design": frozenset({RunRole.brainstorm}),
    "submit_plan": frozenset({RunRole.plan}),
    "complete_step": frozenset({RunRole.implement, RunRole.step_fix}),
    "submit_review": frozenset({RunRole.step_review, RunRole.final_review}),
    "report_finish": frozenset({RunRole.finish}),
    "show_mockup": frozenset({RunRole.brainstorm}),  # also the session resumed to revise a design
}
RUNNER_ONLY = frozenset({"submit_review", "report_finish"})  # connect-only workflows have no such runs

RUN_NEXT: dict[RunRole, str] = {
    RunRole.brainstorm: "Ask questions with ask_human, show screens with show_mockup, then submit_design.",
    RunRole.plan: "Ask questions with ask_human if anything is unclear, then submit_plan with the plan and its steps.",
    RunRole.implement: "Implement step {step}, run its tests, then call complete_step with step={step}.",
    RunRole.step_fix: "Fix the review findings for step {step}, run the tests, then call complete_step with step={step}.",
    RunRole.step_review: "Review step {step}, then call submit_review with your verdict and findings.",
    RunRole.final_review: "Review the whole change, then call submit_review with your verdict and findings.",
    RunRole.final_fix: "Fix the final review's findings and run the tests; your run ends when you are done.",
    RunRole.finish: "Re-verify the tests, perform the finishing option ({option}), then call report_finish.",
}
WAIT_NEXT: dict[Needs, str] = {
    Needs.question: "Wait for the human's answer (it appears in get_task), then call get_workflow again.",
    Needs.design_approval: "Wait for a human to approve or reject the design, then call get_workflow again.",
    Needs.plan_approval: "Wait for a human to approve or reject the plan, then call get_workflow again.",
}
STAGE_NEXT: dict[Stage, str] = {
    Stage.brainstorm: "Ask questions with ask_human, then submit_design.",
    Stage.design: "Revise the design as the rejection asks (read it with get_task), then submit_design.",
    Stage.plan: "Ask questions with ask_human if anything is unclear, then submit_plan with the plan and its steps.",
    Stage.build: "Implement step {step} of {total}, run its tests, then call complete_step with step={step}.",
}


async def _task(db: AsyncSession, user: User, key: str, tool: str, *, write: bool) -> Task:
    """The task a workflow tool acts on, within the caller's scope. A run token is checked before the key is
    looked up at all."""
    run = current_run.get()
    if run is not None:
        await require_run_task(db, key)
        if run.workflow_role is None or RunRole(run.workflow_role) not in TOOL_ROLES[tool]:
            raise ToolError("not_allowed_in_role")
    elif tool in RUNNER_ONLY:
        raise ToolError("not_allowed_in_role")
    task, _ = await get_task_for(db, user, key, write=write)
    if run is not None and task.id != run.task_id:  # defence in depth: require_run_task compared the keys
        raise ToolError("wrong_task")
    return task


async def _readable(db: AsyncSession, user: User, key: str, tool: str) -> tuple[Task, TaskWorkflow | None]:
    task = await _task(db, user, key, tool, write=False)
    wf = await db.get(TaskWorkflow, task.id)
    if current_run.get() is None:
        engine.check_connect_only(user, task, wf)
    return task, wf


async def _workflow_view(db: AsyncSession, task: Task, wf: TaskWorkflow | None) -> dict[str, Any]:
    stage = Stage(wf.stage) if wf else Stage.brainstorm
    wf_status = WorkflowStatus(wf.status) if wf else WorkflowStatus.idle
    needs = Needs(wf.needs) if wf and wf.needs else None
    step = wf.current_step if wf else None
    approved = (
        await db.execute(
            select(WorkflowDocument)
            .where(WorkflowDocument.task_id == task.id, WorkflowDocument.status == DocStatus.approved)
            .order_by(WorkflowDocument.kind, WorkflowDocument.version)
        )
    ).scalars().all()
    plan = next((d for d in reversed(approved) if d.kind == DocKind.plan), None)
    total = len(plan.steps or []) if plan else None
    out: dict[str, Any] = {
        "stage": stage.value,
        "status": wf_status.value,
        "needs": needs.value if needs else None,
        "current_step": step,
        "steps_total": total,
        "documents": [{"kind": str(d.kind), "version": d.version} for d in approved],
    }
    run = current_run.get()
    if run is not None:
        role = RunRole(run.workflow_role)
        option = engine.finishing_option(await db.get(Project, task.project_id), wf) if wf else None
        # the very text its prompt was built from (a design revision's own, unchanged by a later admin edit)
        meth = await db.get(MethodologyVersion, run.methodology_version_id) if run.methodology_version_id else None
        out["role"] = role.value
        out["instructions"] = (meth or await methodology.current(db, ROLE_KEY[role])).body_md
        out["next"] = RUN_NEXT[role].format(step=run.step, option=option.value if option else "")
        return out
    texts = [(k, (await methodology.current(db, k)).body_md.strip()) for k in methodology.KEYS[stage]]
    out["instructions"] = "\n\n".join(f"## {k}\n\n{body}" for k, body in texts)
    if wf_status == WorkflowStatus.finished:
        out["next"] = "The workflow is finished; there is nothing left to do."
    elif wf_status == WorkflowStatus.waiting_human and needs in WAIT_NEXT:
        out["next"] = WAIT_NEXT[needs]
    else:
        out["next"] = STAGE_NEXT.get(stage, "Call get_workflow again later.").format(step=step, total=total)
    return out


def register_workflow_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def get_workflow(key: str) -> dict[str, Any]:
        """The task's workflow: stage, status, what it waits for (needs), the current build step, the approved
        documents, the methodology instructions to follow now, and what to do next."""
        async with tool_session() as (db, user):
            task, wf = await _readable(db, user, key, "get_workflow")
            return await _workflow_view(db, task, wf)

    @mcp.tool()
    async def get_document(key: str, kind: str, version: int | None = None) -> dict[str, Any]:
        """A design or plan document (`kind` is design or plan) with its body and steps; the latest version
        unless `version` is given. A decided one carries the reviewer's comment (why it was rejected) and who
        decided."""
        async with tool_session() as (db, user):
            task, _ = await _readable(db, user, key, "get_document")
            try:
                kind = DocKind(kind)
            except ValueError:
                raise ToolError("invalid_kind") from None
            stmt = select(WorkflowDocument).where(WorkflowDocument.task_id == task.id, WorkflowDocument.kind == kind)
            if version is not None:
                stmt = stmt.where(WorkflowDocument.version == version)
            doc = (await db.execute(stmt.order_by(WorkflowDocument.version.desc()).limit(1))).scalar_one_or_none()
            if doc is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "document_not_found")
            return {
                "kind": str(doc.kind), "version": doc.version, "status": str(doc.status), "body_md": doc.body_md,
                "steps": list(doc.steps) if doc.steps is not None else None,
                "decision_comment": doc.decision_comment,
                "decided_by": str(doc.decided_by) if doc.decided_by else None,
            }

    @mcp.tool()
    async def ask_human(
        key: str,
        question: str,
        choices: list[dict[str, Any]] | None = None,
        mockup_html: str | None = None,
        mockup_title: str | None = None,
        mockup_choices: list[str] | None = None,
    ) -> str:
        """Ask a human a question, then end your turn. `choices`: up to 6 of {id, label, description?,
        recommended?}. An optional HTML mockup (with a title) is shown sandboxed; elements with
        data-megoo-choice="<id>" pick one of `mockup_choices`."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "ask_human", write=True)
            mockup = None
            if mockup_html is not None or mockup_title is not None or mockup_choices:
                mockup = {"html": mockup_html, "title": mockup_title, "choices": mockup_choices}
            # the workflow lock before the question rows: the order questions.answer takes them in
            if current_run.get() is not None:
                await questions.ask(db, await live_run(db, task), task, question, choices, mockup)
            else:
                wf = await engine.lock_connect_only(db, user, task)
                if wf.status == WorkflowStatus.finished:
                    raise HTTPException(status.HTTP_409_CONFLICT, "workflow_finished")
                await questions.ask(db, None, task, question, choices, mockup)
                if wf.status == WorkflowStatus.running:  # an approval it already waits for stays the need
                    await engine.wait_for(db, wf, Needs.question)
            return ASKED

    @mcp.tool()
    async def show_mockup(key: str, html: str, title: str) -> dict[str, Any]:
        """Show the next version of a mockup (one self-contained HTML document, at most 2 MB, and a title) to the
        people on the task, without asking anything: keep working. Refused while a design awaits approval."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "show_mockup", write=True)
            if current_run.get() is not None:
                row = await mockups.show(db, await live_run(db, task), task, html, title)
            else:
                wf = await engine.lock_connect_only(db, user, task)
                if wf.status == WorkflowStatus.finished:
                    raise HTTPException(status.HTTP_409_CONFLICT, "workflow_finished")
                if wf.stage not in (Stage.brainstorm, Stage.design):
                    raise HTTPException(status.HTTP_409_CONFLICT, "wrong_stage")
                row = await mockups.show(db, None, task, html, title)
            return {"version": row.version}

    @mcp.tool()
    async def submit_design(key: str, markdown: str) -> dict[str, Any]:
        """Submit your design (markdown, at most 200,000 characters) for a human's approval."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "submit_design", write=True)
            doc = await _submit(db, user, task, DocKind.design, markdown, None)
            return {"kind": str(doc.kind), "version": doc.version, "status": str(doc.status)}

    @mcp.tool()
    async def submit_plan(key: str, markdown: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit your plan (markdown) with 1-50 steps, each {title, detail}, for a human's approval."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "submit_plan", write=True)
            doc = await _submit(db, user, task, DocKind.plan, markdown, steps)
            return {"kind": str(doc.kind), "version": doc.version, "status": str(doc.status)}

    @mcp.tool()
    async def complete_step(
        key: str, step: int, summary: str, tests_passed: bool, test_command: str | None = None
    ) -> dict[str, Any]:
        """Report the current plan step done: a summary (at most 2,000 characters), whether its tests pass, and
        the test command you ran."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "complete_step", write=True)
            if current_run.get() is not None:
                run = await live_run(db, task)
                await build.complete_step(db, run, step, summary, tests_passed, test_command)
            else:
                wf = await engine.lock_connect_only(db, user, task)
                await build.complete_step_connect_only(db, wf, task, step, summary, tests_passed, test_command)
            return {"step": step, "tests_passed": tests_passed}

    @mcp.tool()
    async def submit_review(key: str, verdict: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
        """Give your review verdict (approved or changes_requested) with up to 50 findings, each {severity
        (critical, important or minor), file, line, summary}."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "submit_review", write=True)
            review = await build.submit_review(db, await live_run(db, task), verdict, findings)
            return {"review_id": str(review.id), "verdict": str(review.verdict), "round": review.round}

    @mcp.tool()
    async def report_finish(
        key: str, outcome: str, branch: str, tests_passed: bool, pr_url: str | None = None
    ) -> dict[str, Any]:
        """Report how you finished: `outcome` is merged_local, pr_opened or branch_kept (as the finishing option
        says), the branch, the pull request URL for pr_opened, and whether the tests pass."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "report_finish", write=True)
            await finish.report_finish(db, await live_run(db, task), outcome, branch, pr_url, tests_passed)
            return {"outcome": outcome, "branch": branch, "tests_passed": tests_passed}


async def _submit(
    db: AsyncSession, user: User, task: Task, kind: DocKind, markdown: str, steps: list[dict] | None
) -> WorkflowDocument:
    if current_run.get() is not None:
        return await documents.submit(db, await live_run(db, task), task, kind, markdown, steps)
    wf = await engine.lock_connect_only(db, user, task)
    return await documents.submit_connect_only(db, wf, task, kind, markdown, steps)
