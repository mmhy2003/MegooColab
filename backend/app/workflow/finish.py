"""Review and Done stages (WF-5, WF-6a, WF-6b).

Review (entered from build.enter_review, round 1):
  final_review (fresh)
    approved           -> Done
    changes_requested  -> round 1: final_fix (fresh, with the findings), and when it ends, final_review round 2
                          (it sees round 1's findings); round 2: escalation final_review_not_clean
                          (`accept` enters Done)
    no verdict         -> one nudge, then escalation review_incomplete
  final_fix has no completion tool: its run simply ends. A failed one falls under the normal retries.
  A fix round on the tests that failed at finish (MC-98, the `fix` action on finish_tests_failed) comes back from
  Done to Review: final_fix (fresh) with the finish_fix text, then final_review with the finish_fix_review text,
  review_round 2 + the round; finish_tests carries the running round (`fix_round`).

Done:
  finish (fresh) states the effective finishing option and ends with report_finish (or report_test_failures).
    reported with passing tests, or failing tests that are known (start commit, flaky) and tolerated, or covered
    by an acceptance          -> human code review required: wait on human_code_review; else finished
    reported otherwise        -> escalation finish_tests_failed (accept: Finish anyway; retry: a fresh finish;
                                 fix: a fix round (MC-98), while nothing was delivered)
    report_test_failures      -> escalation finish_tests_failed, not delivered (Finish anyway resumes the session
                                 to deliver)
    no report                 -> one nudge, then escalation finish_incomplete

`wf.review_round` is the final review's round (build.enter_review sets 1; the final_fix handler sets 2).
"""

import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.audit import service as audit
from app.auth.models import User
from app.core.text import strip_nul
from app.git.models import PR_BACK_MERGE
from app.kb import filing
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import (
    ColumnCategory,
    Project,
    ProjectRepository,
    PrReview,
    RepoProvider,
)
from app.tasks.models import Task
from app.workflow import build, engine, questions
from app.workflow.context import wrap_untrusted
from app.workflow.models import (
    MERGE_WAITS,
    Driver,
    FinishingOption,
    Needs,
    QuestionStatus,
    ReviewScope,
    RunRole,
    Stage,
    StepReview,
    TaskWorkflow,
    Verdict,
    WorkflowQuestion,
    WorkflowStatus,
    WorkflowTestRun,
)

MAX_BRANCH = 200
MAX_PR_URL = 500
KINDS = ("new", "base", "flaky")
MAX_FAILURES = 20
MAX_FAILURE_NAME = 300
MAX_DIAGNOSIS = 2000
MAX_FINISH_FIX_ROUNDS = 2
_SHA = re.compile(r"[0-9a-f]{7,64}")

BRANCH_PUSHED = "branch_pushed"
FINISH_NUDGE = (
    "Re-verify the tests, perform the finishing option, then call report_finish (or report_test_failures when a "
    "failing test needs a person)."
)
OUTCOME_OF = {
    FinishingOption.merge_local: "merged_local",
    FinishingOption.pull_request: "pr_opened",
    FinishingOption.keep_branch: "branch_kept",
}


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


# ---- Review ----------------------------------------------------------------------------------


def fix_round(wf: TaskWorkflow) -> int | None:
    """The running fix round's number (MC-98): the stage is Review and finish_tests carries it; else None."""
    if wf.stage != Stage.review:
        return None
    return (wf.finish_tests or {}).get("fix_round")


def _failures_block(ft: dict) -> str:
    """The failing tests (name and kind), "and N more", and the finish agent's diagnosis: agent-written, so
    one untrusted block."""
    failures = ft.get("failures") or []
    lines = [f"- {f['name']} ({f['kind']})" for f in failures]
    more = (ft.get("failing_total") or 0) - len(failures)
    if more > 0:
        lines.append(f"and {more} more")
    text = "\n".join(lines) or "(the finish named no tests)"
    if ft.get("diagnosis"):
        text += f"\n\nDiagnosis:\n{ft['diagnosis']}"
    return wrap_untrusted("finish_failures", text)


async def fix_section(db: AsyncSession, wf: TaskWorkflow, task: Task) -> str:
    """The fix run's section: the round, the start branch, the failures and diagnosis, the Done stage's test runs."""
    from app.workflow import records  # local: records imports the engine, which imports this module

    ft = wf.finish_tests or {}
    rows = list((await db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.task_id == task.id, WorkflowTestRun.stage == Stage.done)
        .order_by(WorkflowTestRun.created_at, WorkflowTestRun.id)
    )).scalars())
    return (
        f"## Tests that failed at finish\nFix round {ft.get('fix_round')} of {MAX_FINISH_FIX_ROUNDS}\n"
        f"Start branch: {task.start_branch or engine.UNKNOWN_START}\n{_failures_block(ft)}\n\n"
        + records.test_runs_section(rows)
    )


def fix_review_section(wf: TaskWorkflow) -> str:
    """The review run's section: the round, the failures and diagnosis, and where the fix's commits start."""
    ft = wf.finish_tests or {}
    base = ft.get("fix_base")
    where = (
        f"The fix is every commit after `{base}`: review `git diff {base}..HEAD`."
        if isinstance(base, str) and _SHA.fullmatch(base)
        else "The commit the fix started from is unknown: find the commits made after the final review with "
             "`git log`, and review only those."
    )
    return (
        f"## The fix to review\nFix round {ft.get('fix_round')} of {MAX_FINISH_FIX_ROUNDS}\n"
        f"{_failures_block(ft)}\n\n{where}"
    )



async def _handle_final_review(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    requester_id = await engine.owner_id(db, run)
    review = (
        await db.execute(select(StepReview).where(StepReview.run_id == run.id).limit(1))
    ).scalar_one_or_none()
    if review is None:
        if not wf.nudged:
            wf.nudged = True
            await engine.rerun(
                db, wf, task, last=run, requested_by=requester_id, resume_kind="nudge", payload=build.REVIEW_NUDGE
            )
        else:
            await engine.escalate(db, wf, "review_incomplete")
        return
    if review.verdict == Verdict.approved:
        owner = await db.get(User, requester_id)
        await filing.file_final_review(db, task, review, summary=f"Final review round {review.round}: approved",
                                       actor=owner)
        await enter_done(db, wf, task, requested_by=requester_id)
    elif review.round < 2:
        wf.nudged = False
        await engine.enqueue(db, wf, task, RunRole.final_fix, requested_by=requester_id)
    else:
        await engine.escalate(db, wf, "final_review_not_clean")


async def _asked_or_answered(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> bool:
    """final_fix and finish may ask a human: wait for the answer, or resume the run's session with an answer
    that arrived while it was running. True when the run's end was handled that way."""
    if await questions.has_open_question(db, run.id):
        await engine.wait_for(db, wf, Needs.question)
        return True
    pending = await questions.undelivered_answer(db, task.id, run.id)
    if pending is not None:
        await questions.deliver(db, wf, task, pending, requested_by=await engine.owner_id(db, run))
        return True
    return False


async def _handle_final_fix(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """The fix round ended: the scoped re-review (round 2) follows, once its work is committed."""
    if await _asked_or_answered(db, wf, task, run):
        return
    if engine.left_uncommitted(run):  # the read-only re-review could neither commit it nor approve it
        await engine.send_back_to_commit(db, wf, task, run)
        return
    wf.review_round = 2
    wf.nudged = False
    await engine.enqueue(db, wf, task, RunRole.final_review, requested_by=await engine.owner_id(db, run))


async def _accept_final_review(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `accept` after the re-review: the human passes the final review."""
    review = (
        await db.execute(
            select(StepReview)
            .where(StepReview.task_id == task.id, StepReview.scope == ReviewScope.final)
            .order_by(StepReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if review is not None:
        await filing.file_final_review(db, task, review, summary=f"Accepted by {user.name}", actor=user)
    await enter_done(db, wf, task, requested_by=user.id)


# ---- Done ------------------------------------------------------------------------------------


async def enter_done(db: AsyncSession, wf: TaskWorkflow, task: Task, *, requested_by: uuid.UUID) -> None:
    """The Done stage: the finish run states the effective option. The card moves when the workflow finishes."""
    await engine.set_stage(db, wf, task, Stage.done)
    project = await db.get(Project, task.project_id)
    # Frozen for the whole Done stage, so a project setting changed meanwhile cannot change this run. The task's
    # override is overwritten on purpose: set_finishing is refused from here on, so it has served its purpose. The
    # known-failures setting (MC-97) is frozen too, and an earlier finish's failing tests are cleared.
    wf.finishing_override = engine.finishing_option(project, wf)
    wf.finish_pr_review = project.pr_review
    wf.finish_requires_human_review = project.pr_review != "none"
    wf.finish_tolerates_known = project.tolerate_known_test_failures
    wf.finish_tests = None
    wf.review_round = 0
    wf.nudged = False
    await engine.enqueue(db, wf, task, RunRole.finish, requested_by=requested_by)


async def finish_workflow(db: AsyncSession, wf: TaskWorkflow, task: Task, actor_id: uuid.UUID | None) -> None:
    wf.status = WorkflowStatus.finished
    wf.needs = None
    wf.escalation_reason = None  # finished from an escalation (a merge seen after merge_not_confirmed) clears it
    wf.finished_at = datetime.now(UTC)
    await engine.move_to_category(db, task, ColumnCategory.done)
    await engine.record_workflow_event(db, task, actor_id, "workflow.finished", {
        "outcome": wf.finish_outcome, "branch": wf.branch, "pr_url": wf.pr_url,
    })
    if task.in_chat:  # the chat asks whether to add the round to the board: its people hear it finished
        from app.chats.service import (
            chat_people,  # local: the chats modules import the workflow
        )

        recipients, link = await chat_people(db, task)
        await notifications.notify(
            db, recipients, Kind.needs_you, title=f"Chat finished: {task.title}"[:200], body=task.title,
            link=link, task_id=task.id, project_id=task.project_id, actor_id=actor_id,
        )


async def report_finish(
    db: AsyncSession, run: AgentRun, outcome: str, branch: str, pr_url: str | None, tests_passed: bool,
    back_merge_branch: str | None = None, back_merge_pr_url: str | None = None, failures=None, failing_total=None,
) -> None:
    """A finish run reports how it finished (MCP tool in Task 11). A later report from the same run replaces it.
    A production fix (the task's back_merge_into is set) also reports its back-merge: the branch, and for a pull
    request its URL; keep_branch delivers nothing, so takes none. With failing tests it lists them (MC-97).
    The caller commits."""
    wf, task = await build.lock_run_role(db, run, (RunRole.finish,))
    project = await db.get(Project, task.project_id)
    option = engine.finishing_option(project, wf)
    allowed = {OUTCOME_OF[option]}
    if option == FinishingOption.pull_request and await _plain_git(db, project.id):
        allowed.add(BRANCH_PUSHED)  # GIT-2/4: no provider to open a pull request on; the branch is pushed
    if outcome not in allowed:
        raise _422("wrong_finish")
    if not isinstance(tests_passed, bool) or not isinstance(branch, str) or (
        pr_url is not None and not isinstance(pr_url, str)
    ):
        raise _422("invalid_finish_result")
    clean = _clean_failures(failures, required=False)
    total = _clean_total(failing_total, len(clean))
    if tests_passed and (clean or total is not None):
        raise _422("invalid_finish_result")
    branch = strip_nul(branch)
    if len(branch) > MAX_BRANCH:
        raise _422("too_large")
    if outcome == OUTCOME_OF[FinishingOption.pull_request]:
        pr_url = strip_nul(pr_url or "").strip()
        if not pr_url:
            raise _422("pr_url_required")
        if len(pr_url) > MAX_PR_URL:
            raise _422("too_large")
        parts = urlsplit(pr_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise _422("invalid_pr_url")
    else:
        pr_url = None
    back_merge_branch, back_merge_pr_url = _back_merge(task, option, outcome, back_merge_branch, back_merge_pr_url)
    run.step_result = {"outcome": outcome, "branch": branch, "pr_url": pr_url, "tests_passed": tests_passed,
                       "back_merge_branch": back_merge_branch, "back_merge_pr_url": back_merge_pr_url,
                       "failures": clean, "failing_total": total}
    wf.branch, wf.pr_url, wf.finish_outcome = branch or None, pr_url, outcome
    wf.back_merge_branch, wf.back_merge_pr_url = back_merge_branch, back_merge_pr_url
    if tests_passed:
        wf.finish_tests = None
    else:
        _store_failures(wf, clean, total, None, delivered=True)
    reported = {"outcome": outcome, "branch": branch, "pr_url": pr_url, "tests_passed": tests_passed}
    if back_merge_branch:  # a production fix's second delivery
        reported |= {"back_merge_branch": back_merge_branch, "back_merge_pr_url": back_merge_pr_url}
    await engine.record_workflow_event(db, task, None, "finish.reported", reported)
    from app.git import service as git  # local: git imports the workflow

    if pr_url:
        await git.track_pr(db, task, pr_url)
    if back_merge_pr_url:
        await git.track_pr(db, task, back_merge_pr_url, kind=PR_BACK_MERGE)


async def report_test_failures(
    db: AsyncSession, run: AgentRun, failures, diagnosis, failing_total=None,
) -> None:
    """A finish run delivered nothing: it reports the failing tests a person must decide on (MC-97). It replaces
    the run's earlier result, and a later report_finish replaces it in turn. The handler records the event. The
    caller commits."""
    wf, _ = await build.lock_run_role(db, run, (RunRole.finish,))
    clean = _clean_failures(failures, required=True)
    total = _clean_total(failing_total, len(clean))
    text = _clean_diagnosis(diagnosis)
    run.step_result = {"test_failures": clean, "failing_total": total, "diagnosis": text}
    _store_failures(wf, clean, total, text, delivered=False)


def _clean_failures(value, *, required: bool) -> list[dict]:
    """The agent's failing tests: [{name, kind}], at most 20; refused when malformed (invalid_finish_result) or
    oversize (too_large)."""
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise _422("invalid_finish_result")
    if len(value) > MAX_FAILURES:
        raise _422("too_large")
    out = []
    for entry in value:
        name = entry.get("name") if isinstance(entry, dict) else None
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if not isinstance(name, str) or kind not in KINDS:
            raise _422("invalid_finish_result")
        name = strip_nul(name).strip()
        if not name:
            raise _422("invalid_finish_result")
        if len(name) > MAX_FAILURE_NAME:
            raise _422("too_large")
        out.append({"name": name, "kind": kind})
    if required and not out:
        raise _422("invalid_finish_result")
    return out


def _clean_total(value, listed: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < listed:
        raise _422("invalid_finish_result")
    return value


def _clean_diagnosis(value) -> str:
    if not isinstance(value, str) or not strip_nul(value).strip():
        raise _422("invalid_finish_result")
    value = strip_nul(value).strip()
    if len(value) > MAX_DIAGNOSIS:
        raise _422("too_large")
    return value


def _store_failures(wf, failures, failing_total, diagnosis, *, delivered: bool) -> None:
    """A new report replaces the stored one. An acceptance is kept until the finish handler compares it with the report.
    Always a new dict: the JSONB column does not track changes in place."""
    kept = {k: v for k, v in (wf.finish_tests or {}).items() if k in ("accepted_by", "accepted_at", "accepted")}
    wf.finish_tests = {"failures": failures, "failing_total": failing_total, "diagnosis": diagnosis,
                       "delivered": delivered, "settled": None, **kept}


def _pr_url(url: str, missing: str) -> str:
    url = strip_nul(url or "").strip()
    if not url:
        raise _422(missing)
    if len(url) > MAX_PR_URL:
        raise _422("too_large")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise _422("invalid_pr_url")
    return url


def _back_merge(
    task: Task, option: FinishingOption, outcome: str, branch: str | None, pr_url: str | None
) -> tuple[str | None, str | None]:
    """The checked back-merge result: required for a production fix that delivers (not keep_branch), refused
    otherwise. A pull request needs its URL; a local merge or a plain push does not."""
    if not task.back_merge_into or option == FinishingOption.keep_branch:
        if branch is not None or pr_url is not None:
            raise _422("back_merge_not_expected")
        return None, None
    if not isinstance(branch, str) or not strip_nul(branch).strip():
        raise _422("back_merge_required")
    branch = strip_nul(branch).strip()
    if len(branch) > MAX_BRANCH:
        raise _422("too_large")
    if outcome == OUTCOME_OF[FinishingOption.pull_request]:
        if pr_url is not None and not isinstance(pr_url, str):
            raise _422("invalid_finish_result")
        return branch, _pr_url(pr_url, "back_merge_pr_url_required")
    if pr_url is not None:
        raise _422("back_merge_not_expected")
    return branch, None


async def _plain_git(db: AsyncSession, project_id: uuid.UUID) -> bool:
    """No repository of the project is on GitHub, GitLab or Gitea/Forgejo (GIT-1): plain git only."""
    hosted = await db.scalar(
        select(ProjectRepository.id).where(
            ProjectRepository.project_id == project_id, ProjectRepository.provider != RepoProvider.plain
        ).limit(1)
    )
    return hosted is None


async def _move_on(db: AsyncSession, wf: TaskWorkflow, task: Task) -> None:
    """The finish is settled: wait for the pull request when its review or a back-merge requires it, else
    finished."""
    project = await db.get(Project, task.project_id)
    # a production fix waits for both pull requests to merge, whether or not review is required
    waits = engine.requires_human_review(project, wf) or bool(
        wf.back_merge_pr_url and wf.finish_outcome == OUTCOME_OF[FinishingOption.pull_request]
    )
    if waits and engine.finishing_option(project, wf) == FinishingOption.pull_request:
        from app.git import service as git  # local: git imports the workflow

        agent_reviews = engine.pr_review_mode(project, wf) == PrReview.agent
        await engine.wait_for(db, wf, Needs.human_code_review, notify=not agent_reviews)
        # a tracked pull request merged (or closed) before this run ended moves on at once; else an agent reviews
        # it when the project asks for one (piece 4)
        if not await git.settle_done(db, wf, task, await git.pull_requests_of_task(db, task.id)):
            from app.git import agent_review  # local: git imports the workflow

            await agent_review.review_if_agent(db, wf, task)
    else:
        await finish_workflow(db, wf, task, None)


async def _handle_finish(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    if await _asked_or_answered(db, wf, task, run):
        return
    result = run.step_result or {}
    if result.get("tests_passed") is True:
        await _move_on(db, wf, task)
    elif "tests_passed" in result:  # delivered with failing tests
        await _settle_delivered(db, wf, task, run)
    elif "test_failures" in result:  # report_test_failures: nothing delivered
        await _raise_card(db, wf, task, delivered=False)
    elif not wf.nudged:
        wf.nudged = True
        await engine.rerun(
            db, wf, task, last=run, requested_by=await engine.owner_id(db, run), resume_kind="nudge",
            payload=FINISH_NUDGE,
        )
    else:
        await engine.escalate(db, wf, "finish_incomplete")


def _needs_person(ft: dict, tolerated: bool) -> list[dict]:
    """The failures a person must decide on: the new ones, or all of them when known ones are not tolerated or
    the list does not name every failing test."""
    failures = ft.get("failures") or []
    complete = ft.get("failing_total") is None or ft["failing_total"] <= len(failures)
    if not tolerated or not complete:
        return failures
    return [f for f in failures if f["kind"] == "new"]


def _covered(ft: dict, tolerated: bool) -> bool:
    """Every failure that needs a person was accepted on the card in this Done round (no names: any acceptance)."""
    if not ft.get("accepted_by"):
        return False
    return {f["name"] for f in _needs_person(ft, tolerated)} <= set(ft.get("accepted") or [])


async def _settle_delivered(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """The finish delivered with failing tests: it moves on when they are known and tolerated, or accepted;
    else the card."""
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    project = await db.get(Project, task.project_id)
    tolerated = engine.tolerates_known(project, wf)
    failures = ft.get("failures") or []
    if failures and not _needs_person(ft, tolerated):
        wf.finish_tests = {**ft, "settled": "known"}
        await engine.record_workflow_event(db, task, None, "finish.known_failures",
                                           {"failures": failures, "start_branch": task.start_branch})
    elif _covered(ft, tolerated):
        wf.finish_tests = {**ft, "settled": "accepted"}
    elif (answerer := await _answered_in_session(db, task, run)) is not None:
        await _accept_names(db, wf, task, answerer, via="answer", settled="accepted")
    else:
        await _raise_card(db, wf, task, delivered=True)
        return
    await _move_on(db, wf, task)


async def _answered_in_session(db: AsyncSession, task: Task, run: AgentRun) -> uuid.UUID | None:
    """The person who answered a question of the finish session this run resumed: their answer let it deliver."""
    if not run.resume_session_ref:
        return None
    return await db.scalar(
        select(WorkflowQuestion.answered_by)
        .join(AgentRun, AgentRun.id == WorkflowQuestion.run_id)
        .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.answered,
               AgentRun.workflow_role == RunRole.finish, AgentRun.session_ref == run.resume_session_ref)
        .order_by(WorkflowQuestion.answered_at.desc())
        .limit(1)
    )


async def _accept_names(
    db: AsyncSession, wf: TaskWorkflow, task: Task, user_id: uuid.UUID, *, via: str, settled: str | None
) -> None:
    """Record who accepted which failing tests: on the workflow, an event and an audit entry."""
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    names = [f["name"] for f in ft.get("failures") or []]
    wf.finish_tests = {**ft, "accepted_by": str(user_id), "accepted_at": datetime.now(UTC).isoformat(),
                       "accepted": names, "settled": settled}
    await engine.record_workflow_event(db, task, user_id, "finish.failures_accepted", {
        "failures": ft.get("failures") or [], "failing_total": ft.get("failing_total"), "via": via})
    await audit.record(db, "workflow.finish_failures_accepted", actor_id=user_id, target_type="task",
                       target_id=task.id, data={"names": names, "failing_total": ft.get("failing_total"), "via": via})


async def _raise_card(db: AsyncSession, wf: TaskWorkflow, task: Task, *, delivered: bool) -> None:
    """The finish_tests_failed card: a person decides on the failing tests. An earlier acceptance is dropped."""
    ft = {k: v for k, v in (wf.finish_tests or {"failures": []}).items()
          if k not in ("accepted_by", "accepted_at", "accepted")}
    wf.finish_tests = {**ft, "delivered": delivered, "settled": None}
    await engine.record_workflow_event(db, task, None, "finish.tests_failed", {
        "failures": ft.get("failures") or [], "failing_total": ft.get("failing_total"), "delivered": delivered,
        "start_branch": task.start_branch})
    await engine.escalate(db, wf, "finish_tests_failed")


async def _accept_tests_failed(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `accept` ("Finish anyway"): the person accepts the failing tests. Delivered: the finish moves on.
    Not delivered: the reporting session resumes to deliver and list them (a fresh prompt when it has no session)."""
    ft = wf.finish_tests or {"failures": [], "delivered": True}
    delivered = ft.get("delivered", True)
    await _accept_names(db, wf, task, user.id, via="card", settled="accepted" if delivered else None)
    if delivered:
        await _move_on(db, wf, task)
        return
    wf.nudged = False
    last = await engine.latest_run(db, task.id)
    session = last.session_ref if last is not None and last.workflow_role == RunRole.finish else None
    await engine.enqueue(
        db, wf, task, RunRole.finish, resume_kind="failures_accepted", requested_by=user.id,
        payload={"by": user.name, "names": [f["name"] for f in ft.get("failures") or []],
                 "failing_total": ft.get("failing_total")},
        resume_session_ref=session,
    )


async def _retry_tests_failed(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `retry`: forget the report and its acceptance, and run the finish again from the start."""
    wf.finish_tests = None
    await engine.enqueue(db, wf, task, RunRole.finish, requested_by=user.id)


# ---- human decisions (WF-6) -------------------------------------------------------------------


async def _fix_tests_failed(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """Escalation `fix` (MC-98): a fresh final_fix on the failing tests, in the Review stage; its review and a
    fresh finish follow. Only while nothing was delivered, at most MAX_FINISH_FIX_ROUNDS per task."""
    ft = wf.finish_tests or {}
    if ft.get("delivered", True):
        raise _422("cannot_fix_here")
    used = wf.finish_fix_rounds or 0
    if used >= MAX_FINISH_FIX_ROUNDS:
        raise _422("fix_rounds_exhausted")
    n = used + 1
    wf.finish_fix_rounds = n
    kept = {k: v for k, v in ft.items() if k not in ("accepted_by", "accepted_at", "accepted", "fix_base")}
    wf.finish_tests = {**kept, "fix_round": n}
    await engine.record_workflow_event(db, task, None, "finish.fix_started", {
        "round": n, "of": MAX_FINISH_FIX_ROUNDS, "failures": ft.get("failures") or [],
        "failing_total": ft.get("failing_total")})
    await engine.set_stage(db, wf, task, Stage.review)
    wf.review_round = 2 + n  # the final review's rounds 1 and 2 came before: each final review has its own round
    await engine.enqueue(db, wf, task, RunRole.final_fix, requested_by=user.id)


async def approve_human_review(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """A human clicked "PR approved" (or Mark merged, while an agent's merge is being confirmed): the workflow
    finishes. The first approval wins."""
    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    needed_review = wf is not None and wf.finish_requires_human_review is True
    if needed_review and wf.status == WorkflowStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs not in MERGE_WAITS:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_waiting_for_decision")
    await mark_merged(db, wf, task, user)
    return wf


async def mark_merged(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """A person says the pull request merged: recorded, and the workflow finishes. The caller holds the workflow
    lock and has checked that it waits for the merge."""
    await engine.record_workflow_event(db, task, user.id, "human_review.approved", {"pr_url": wf.pr_url})
    await audit.record(
        db, "workflow.human_review_approved", actor_id=user.id, target_type="task", target_id=task.id,
        data={"pr_url": wf.pr_url},
    )
    await finish_workflow(db, wf, task, user.id)


async def set_finishing(db: AsyncSession, user: User, task: Task, option: FinishingOption | None) -> TaskWorkflow:
    """The task-level override of the project's finishing option, allowed until the Done stage."""
    wf = await engine.lock_task(db, task)  # never creates one: an idle row would block human board moves
    await engine.require_actor(db, user, task, wf)
    if wf is None or wf.driver != Driver.runner or wf.status == WorkflowStatus.idle:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_started")
    if wf.stage == Stage.done:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_past_finishing")
    wf.finishing_override = option
    await engine.record_workflow_event(
        db, task, user.id, "finishing.changed", {"option": option.value if option else None}
    )
    return wf


async def _accept_pr_closed(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """A pull request (the main or the back-merge one) was closed without merging and a person accepts the work
    as done anyway."""
    await finish_workflow(db, wf, task, user.id)


engine.ROLE_HANDLERS[RunRole.final_review] = _handle_final_review
engine.ROLE_HANDLERS[RunRole.final_fix] = _handle_final_fix
engine.ROLE_HANDLERS[RunRole.finish] = _handle_finish
engine.ACCEPT_HANDLERS["final_review_not_clean"] = _accept_final_review
engine.ACCEPT_HANDLERS["pr_closed"] = _accept_pr_closed
engine.ACCEPT_HANDLERS["back_merge_pr_closed"] = _accept_pr_closed
engine.ACCEPT_HANDLERS["finish_tests_failed"] = _accept_tests_failed
engine.RETRY_HANDLERS["finish_tests_failed"] = _retry_tests_failed
engine.FIX_HANDLERS["finish_tests_failed"] = _fix_tests_failed
