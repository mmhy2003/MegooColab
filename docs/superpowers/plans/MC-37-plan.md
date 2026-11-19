# MC-37 implementation plan: every running run on the Agents pages, link first in "Running now"

## Goal
Both Agents pages list every task, chat, question, cron and draft an agent is working on, each as a link. The Dashboard's "Running now" rows begin with that link, on two lines.

## Architecture
- **Backend.** `backend/app/agent_runs/running.py` is the one query that describes "a run at work now" as a `RunningItem` (moved to `app/agent_runs/schemas.py`, with new fields `kind`, `title`, `question_key` and a nullable `link`). The Dashboard calls it with its scope filter. `agents/service.py::_base_fields` calls it with the agents' ids and fills the new `AgentOut.runs`, for the owner and for admins only. `AdminAgentOut.current_run` and its two queries go away.
- **Frontend.** `src/lib/runs.ts` holds the stage labels, the status text and the ticking-clock hook. `components/runs/RunLink.tsx` draws the link part. `components/runs/WorkingOn.tsx` draws an agent's list, optionally collapsed to the newest run plus "+N more". RunningNow, Admin → Agents and My agents only arrange these pieces.

## Conventions for every step
- Work on the current branch `megoo/MC-37-ui-ux-improvements` (it comes from `develop`). One commit per step. The subject is the one given in the step. The body says why and what in plain sentences, and the message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and watch it fail, implement, then run it again.
- Backend checks: `cd backend; uv run pytest <files> -q`, and the full `uv run pytest -q` before committing. Never start two pytest runs at the same time.
- Frontend checks: `cd frontend; npx tsc --noEmit; npx eslint <changed files>; npm test`. Don't run Prettier.
- **`frontend/src/lib/api-types.ts` is regenerated (`cd frontend; npm run gen:api`) only in steps 3 and 5.** Those are the steps whose frontend code consumes the changed schema. Steps 1 and 2 change the API but leave the generated types alone, so `tsc` stays green between steps.
- Import cycles: `app.chats.service` imports `app.agents.service`. So `agents/service.py` imports the shared query **inside** `_base_fields`, with a comment, like the existing `from app.a2a.models import Question  # local: a2a imports this module`. `running.py` itself imports everything at the top.

## File map
| File | Change | Responsibility |
|---|---|---|
| `backend/app/agent_runs/schemas.py` | modify | `RunKind`, `RunningItem` (moved here, new fields) |
| `backend/app/agent_runs/running.py` | create | `run_targets`, `run_project_id`, `running_items`, `running_by_agent` |
| `backend/app/dashboard/schemas.py` | modify | drop its own `RunningItem`, import it from `app.agent_runs.schemas` |
| `backend/app/dashboard/agents.py` | modify | `_in_scope`, `_runs` on `run_targets`, `running()` calls `running_items` |
| `backend/app/agents/schemas.py` | modify | `AgentOut.runs`; `AdminAgentOut` loses `current_run` (step 5) |
| `backend/app/agents/service.py` | modify | `_base_fields` fills `runs`; `_newest` and the admin queries removed (step 5) |
| `backend/tests/dashboard/conftest.py` | modify | helpers `add_chat`, `add_cron_run`, `add_draft`; `add_task(chat=)`, `add_run(cron_run=, draft=)` |
| `backend/tests/dashboard/test_agents.py` | modify | new running-row tests |
| `backend/tests/agents/test_working_on.py` | create | runs on admin, mine and project agent lists |
| `backend/tests/agents/test_agents.py`, `tests/agent_runs/test_dispatch.py`, `tests/agent_runs/test_audit_and_cancel.py` | modify | read `runs` instead of `current_run` (step 5) |
| `frontend/src/lib/api-types.ts` | regenerate | steps 3 and 5 |
| `frontend/src/lib/runs.ts` (+ `src/lib/__tests__/runs.test.ts`) | create | `STAGE_LABEL`, `runStatus`, `useNow` |
| `frontend/src/components/runs/RunLink.tsx` (+ `__tests__/RunLink.test.tsx`) | create | the link part of a run |
| `frontend/src/components/runs/WorkingOn.tsx` (+ `__tests__/WorkingOn.test.tsx`) | create | an agent's list of runs, optionally collapsed |
| `frontend/src/components/dashboard/RunningNow.tsx` (+ test, `__tests__/fixture.ts`) | modify | two-line rows |
| `frontend/src/components/dashboard/StageBars.tsx` | modify | import `STAGE_LABEL` from `@/lib/runs` |
| `frontend/src/app/(app)/admin/agents/page.tsx` (+ test) | modify | "Working on" column, runs count in Status |
| `frontend/src/components/agents/AgentsTab.tsx` (+ test) | modify | "Working on" section in `AgentDetails` |
| `frontend/e2e/parallel.spec.ts` | modify | both Agents pages list the three runs |

## Code A: `backend/app/agent_runs/schemas.py` additions
```python
from typing import Literal
from app.workflow.models import Stage

RunKind = Literal["task", "chat", "question", "cron", "draft"]


class RunningItem(BaseModel):
    """A run at work now, as the Dashboard's Running now and the Agents pages list it."""

    run_id: uuid.UUID
    agent_name: str
    started_at: datetime | None
    kind: RunKind
    title: str | None = None  # the task's title, the chat's title or the cron's name
    task_key: str | None
    question_key: str | None = None  # answering runs: <KEY>-Q<n>
    stage: Stage | None
    step: int | None
    steps_total: int | None
    review_round: int | None
    question_from: str | None  # answering runs: the asking task's project key
    link: str | None  # None: a Knowledge Base draft, or a run in a project the viewer cannot open
    chat_id: uuid.UUID | None = None
```

## Code B: `backend/app/agent_runs/running.py`
```python
"""Runs at work now, described once for every screen that lists them: the Dashboard's Running now and the Agents
pages. A run works on a task (or a chat's round), answers a question, runs a cron or writes a Knowledge Base draft."""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.a2a.models import Question
from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.schemas import RunningItem
from app.agents.models import Agent
from app.chats.models import Chat
from app.chats.service import chat_link
from app.crons.models import Cron, CronRun
from app.dashboard.scope import task_link
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow.models import DocKind, DocStatus, Stage, TaskWorkflow, WorkflowDocument


def run_targets(*columns) -> Select:
    """A select over runs with what each works on joined: its task, its question, or its cron run and cron."""
    return (
        select(*columns).select_from(AgentRun)
        .outerjoin(Task, Task.id == AgentRun.task_id)
        .outerjoin(Question, Question.id == AgentRun.question_id)
        .outerjoin(CronRun, CronRun.id == AgentRun.cron_run_id)
        .outerjoin(Cron, Cron.id == CronRun.cron_id)
    )


def run_project_id() -> ColumnElement[uuid.UUID]:
    """The project a run works in (over run_targets): its task's, its question's target, or its cron's; None for a
    Knowledge Base draft."""
    return func.coalesce(Task.project_id, Question.target_project_id, Cron.project_id)


async def _running(
    db: AsyncSession, where: ColumnElement[bool], openable: Collection[uuid.UUID] | None
) -> list[tuple[uuid.UUID, RunningItem]]:
    """(agent id, item) for each running run matching `where`, newest started first. `openable`: the projects the
    viewer can open (None: all); a run elsewhere keeps its text but loses its link."""
    asking_task, asking_project = aliased(Task), aliased(Project)
    project_id = run_project_id()
    steps_total = (
        select(func.jsonb_array_length(WorkflowDocument.steps))
        .where(WorkflowDocument.task_id == AgentRun.task_id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc()).limit(1).scalar_subquery()
    )
    stmt = (
        run_targets(AgentRun.agent_id, AgentRun.id, Agent.name, AgentRun.started_at, project_id, Project.key,
                    Task.number, Task.title, Task.chat_id, Task.in_chat, Chat.title, AgentRun.stage, AgentRun.step,
                    steps_total, TaskWorkflow.review_round, AgentRun.question_id, Question.number,
                    asking_project.key, Cron.id, Cron.name)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .outerjoin(Project, Project.id == project_id)
        .outerjoin(Chat, Chat.id == Task.chat_id)
        .outerjoin(TaskWorkflow, TaskWorkflow.task_id == AgentRun.task_id)
        .outerjoin(asking_task, asking_task.id == Question.from_task_id)
        .outerjoin(asking_project, asking_project.id == asking_task.project_id)
        .where(AgentRun.status == RunStatus.running, where)
        .order_by(AgentRun.started_at.desc().nulls_last(), AgentRun.id)
    )
    out = []
    for (agent_id, run_id, name, started, pid, key, number, task_title, chat_id, in_chat, chat_title, stage, step,
         total, rounds, question_id, question_number, asked_from, cron_id, cron_name) in (await db.execute(stmt)).all():
        title = question_key = link = None
        if number is not None and in_chat and chat_id:  # a chat's round; added to the board it is a plain task
            kind, title, link = "chat", chat_title, chat_link(chat_id)
        elif number is not None:
            kind, title, link = "task", task_title, task_link(key, number)
        elif question_id is not None:
            kind, question_key, link = "question", f"{key}-Q{question_number}", f"/questions/{question_id}"
        elif cron_id is not None:
            kind, title, link = "cron", cron_name, f"/projects/{key}/crons/{cron_id}"
        else:
            kind = "draft"  # only the draft's person can open it
        if openable is not None and pid not in openable:
            link = None
        out.append((agent_id, RunningItem(
            run_id=run_id, agent_name=name, started_at=started, kind=kind, title=title,
            task_key=f"{key}-{number}" if number is not None else None, question_key=question_key,
            stage=stage, step=step if stage == Stage.build else None,
            steps_total=total if stage == Stage.build else None,
            review_round=rounds if stage == Stage.review else None,
            question_from=asked_from if question_id else None,
            link=link, chat_id=chat_id if kind == "chat" else None,
        )))
    return out


async def running_items(db: AsyncSession, where: ColumnElement[bool]) -> list[RunningItem]:
    """The running runs matching `where` (a condition over run_targets), newest started first."""
    return [item for _, item in await _running(db, where, None)]


async def running_by_agent(
    db: AsyncSession, agent_ids: Collection[uuid.UUID], openable: Collection[uuid.UUID] | None
) -> dict[uuid.UUID, list[RunningItem]]:
    """Each agent's running runs, drafts and cron runs too, newest started first; agents with none are left out."""
    by_agent: dict[uuid.UUID, list[RunningItem]] = {}
    if agent_ids:
        for agent_id, item in await _running(db, AgentRun.agent_id.in_(set(agent_ids)), openable):
            by_agent.setdefault(agent_id, []).append(item)
    return by_agent
```

## Code C: `backend/app/dashboard/agents.py` changes
```python
from sqlalchemy import and_, exists, func, select
from app.agent_runs.running import run_project_id, run_targets, running_items


def _in_scope(scope: Scope) -> ColumnElement[bool]:
    """Runs in scope, over run_targets: through their project (a task's, a question's target or a cron's)."""
    # a Knowledge Base draft's turns are its person's own: not on anyone's dashboard
    cond = and_(AgentRun.draft_id.is_(None), scope.in_projects(run_project_id()))
    return and_(cond, AgentRun.agent_id.in_(scope.agent_ids)) if scope.name == "mine" else cond


def _runs(scope: Scope, *columns):
    """A select over runs in scope, with the run's task, question and cron joined."""
    return run_targets(*columns).where(_in_scope(scope))


async def running(db: AsyncSession, scope: Scope) -> list[RunningItem]:
    return await running_items(db, _in_scope(scope))
```
Update the module docstring: a run is in scope through its task's project, the question's target project, or its cron's project. Remove the imports that are no longer used (`aliased`, `chat_link`, `Project` only if `queued` stops using it (it still does), `TaskWorkflow`, `WorkflowDocument`, `DocKind`, `DocStatus`, `Stage`). `from sqlalchemy import ColumnElement` is needed for the type hint. `RunningItem` keeps coming from `app.dashboard.schemas`.

## Code D: test helpers in `backend/tests/dashboard/conftest.py`
```python
from app.chats.models import Chat
from app.crons.models import Cron, CronRun
from app.kb import access
from app.kb_drafts.models import KbDraft

# add_task gains `chat: Chat | None = None`: Task(..., chat_id=chat.id if chat else None, in_chat=chat is not None)
# add_run gains `cron_run: CronRun | None = None, draft: KbDraft | None = None`:
#   AgentRun(..., cron_run_id=cron_run.id if cron_run else None, draft_id=draft.id if draft else None)


async def add_chat(db, project: Project, *, title: str = "Chat title") -> Chat:
    chat = Chat(project_id=project.id, title=title)
    db.add(chat)
    await db.commit()
    return chat


async def add_cron_run(db, project: Project, *, name: str = "Nightly check") -> CronRun:
    cron = Cron(project_id=project.id, name=name, prompt="", schedule="0 3 * * *", timezone="UTC")
    db.add(cron)
    await db.flush()
    cron_run = CronRun(cron_id=cron.id, scheduled_at=datetime.now(UTC), status="running")
    db.add(cron_run)
    await db.commit()
    return cron_run


async def add_draft(db, user: User, agent: Agent, project: Project) -> KbDraft:
    space = await access.space_for_project(db, project.id)
    draft = KbDraft(user_id=user.id, agent_id=agent.id, space_id=space.id, brief="A runbook", sources=[])
    db.add(draft)
    await db.commit()
    return draft
```

## Code E: `frontend/src/lib/runs.ts`
```ts
import { useEffect, useState } from "react";

import type { RunningItem } from "@/lib/dashboard";
import { STAGES } from "@/lib/workflow";

/** A run in the Done stage is the finish run. */
export const STAGE_LABEL: Record<string, string> = {
  ...Object.fromEntries(STAGES.map((s) => [s.id, s.label])),
  done: "Finishing",
};

/** What a run with no workflow stage is doing. */
const NO_STAGE: Record<RunningItem["kind"], string> = {
  task: "Working", chat: "Working", question: "Answering", cron: "Running", draft: "Writing",
};

/** A run's status: the stage, with the step in Build and the round past the first in Review. */
export function runStatus(run: RunningItem): string {
  if (!run.stage) return NO_STAGE[run.kind];
  const stage = STAGE_LABEL[run.stage];
  if (run.stage === "build" && run.step && run.steps_total) return `${stage} · Step ${run.step} of ${run.steps_total}`;
  if (run.stage === "review" && run.review_round && run.review_round > 1) return `${stage}, round ${run.review_round}`;
  return stage;
}

/** The time now, ticking every second, for running times counted in the browser. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}
```

## Code F: `frontend/src/components/runs/RunLink.tsx`
```tsx
import Link from "next/link";

import type { RunningItem } from "@/lib/dashboard";

const TAG = { chat: "border-violet text-violet", cron: "border-line text-muted-foreground" } as const;

/** What a run works on, as a link: a task's key, a chat's or cron's tag and title, a question's key. A draft, or a
 *  run the viewer cannot open, is the same text without the link. A key never shortens; a title does. */
export function RunLink({ run }: { run: RunningItem }) {
  const keyed = run.kind === "task" || run.kind === "question";
  const text =
    run.kind === "task" ? run.task_key
    : run.kind === "question" ? run.question_key
    : run.kind === "draft" ? "Knowledge Base draft"
    : run.title;
  const look = keyed ? "shrink-0 font-mono text-xs" : "min-w-0 truncate";
  const tag = run.kind === "chat" || run.kind === "cron" ? run.kind : null;
  return (
    <>
      {tag && <span className={`shrink-0 rounded border px-1 text-[10px] uppercase ${TAG[tag]}`}>{tag}</span>}
      {run.link ? (
        <Link
          href={run.link}
          title={run.kind === "task" ? (run.title ?? undefined) : undefined}
          className={`${look} text-cyan-ink no-underline hover:underline`}
        >
          {text ?? run.kind}
        </Link>
      ) : (
        <span className={look}>{text ?? run.kind}</span>
      )}
    </>
  );
}
```

## Code G: RunningNow row (replaces the `running.map` body)
```tsx
<li key={run.run_id} className="space-y-0.5 py-1.5 text-sm">
  <div className="flex min-w-0 items-center gap-1.5">
    <Dot state="busy" />
    <RunLink run={run} />
    {run.kind === "task" && run.title && <span className="min-w-0 truncate">{run.title}</span>}
  </div>
  <div className="flex min-w-0 items-center gap-2 pl-3.5 text-xs text-muted-foreground">
    <span className="min-w-0 truncate font-semibold text-foreground">{run.agent_name}</span>
    <span className="shrink-0 rounded-full border border-line px-1.5">{runStatus(run)}</span>
    {run.started_at && <span className="ml-auto shrink-0">{shortDuration(now - Date.parse(run.started_at))}</span>}
  </div>
</li>
```

## Code H: `frontend/src/components/runs/WorkingOn.tsx`
```tsx
"use client";

import { useId, useState } from "react";

import { RunLink } from "@/components/runs/RunLink";
import { type RunningItem, shortDuration } from "@/lib/dashboard";
import { runStatus, useNow } from "@/lib/runs";

/** What an agent is working on, newest first. `collapsed`: the newest only, the rest behind "+N more" (the
 *  Admin table keeps its rows one height). `titles`: a task's title after its key. No run: a dash. */
export function WorkingOn({ runs, collapsed = false, titles = false }: { runs: RunningItem[]; collapsed?: boolean; titles?: boolean }) {
  const [open, setOpen] = useState(false);
  const now = useNow();
  const id = useId();
  if (runs.length === 0) return <span className="text-muted-foreground">—</span>;
  const shown = collapsed && !open ? runs.slice(0, 1) : runs;
  return (
    <div className="min-w-0 space-y-1">
      <ul id={id} aria-label="Working on" className="space-y-1">
        {shown.map((run) => (
          <li key={run.run_id} className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
            <RunLink run={run} />
            {titles && run.kind === "task" && run.title && <span className="min-w-0 truncate">{run.title}</span>}
            <span className="shrink-0 text-xs text-muted-foreground">{runStatus(run)}</span>
            {run.started_at && (
              <span className="shrink-0 text-xs text-muted-foreground">{shortDuration(now - Date.parse(run.started_at))}</span>
            )}
          </li>
        ))}
      </ul>
      {collapsed && runs.length > 1 && (
        <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}
          className="text-xs text-cyan-ink hover:underline">
          {open ? "Show less" : `+${runs.length - 1} more`}
        </button>
      )}
    </div>
  );
}
```

## Steps

### 1. Shared running-runs query on the backend; the Dashboard uses it and counts cron runs through their project
See the step detail. It uses Code A to D.

### 2. Agents carry their running runs (`AgentOut.runs`) for the owner and admins
See the step detail.

### 3. Dashboard "Running now": two-line rows with the link first (lib/runs.ts, RunLink)
See the step detail. It uses Code E to G.

### 4. WorkingOn component: an agent's runs, optionally collapsed behind "+N more"
See the step detail. It uses Code H.

### 5. Admin → Agents: "Working on" column and run count; `current_run` removed
See the step detail.

### 6. My agents: "Working on" section on the agent's card
See the step detail.

### 7. Browser test: both Agents pages list an agent's three runs at once
See the step detail.

(The step details in the `steps` array are the full instructions for each step.)

## Final verification
```
cd backend; uv run pytest -q
cd frontend; npx tsc --noEmit; npx eslint src/lib/runs.ts src/components/runs src/components/dashboard/RunningNow.tsx src/components/dashboard/StageBars.tsx "src/app/(app)/admin/agents/page.tsx" src/components/agents/AgentsTab.tsx e2e/parallel.spec.ts; npm test
```
Then run the browser tests on a fresh e2e stack, as AGENTS.md describes (`npx playwright test --reporter=line`). They must all pass, `parallel.spec.ts` included. `dashboard.spec.ts` and `agents.spec.ts` don't read the old row text, so they need no change. They must still pass.

Requirement check:
- Every run is listed on both Agents pages: steps 2, 5 and 6.
- Admin "newest + more": steps 4 and 5.
- My agents not collapsed and hidden when idle: step 6.
- Link first on two lines in "Running now": step 3.
- Cron and draft rules, chat title, question key: steps 1 and 3.
- `link` null when the viewer can't open the run: steps 1 and 2.
- Run count in the Admin status cell: step 5.
- `current_run` removed: step 5.
- Browser tests: step 7.
