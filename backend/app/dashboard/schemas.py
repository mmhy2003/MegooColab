import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.workflow.models import Stage

ScopeName = Literal["mine", "teams", "all"]


class Numbers(BaseModel):
    need_you: int = 0
    need_you_over_day: int = 0
    agents_working: int = 0
    agents_online: int = 0  # online + busy
    runs_queued: int = 0
    workflows_in_progress: int = 0
    workflow_projects: int = 0
    open_tasks: int = 0
    open_in_progress: int = 0  # in working or review columns
    done_7d: int = 0
    done_prev_7d: int = 0
    overdue: int = 0
    overdue_mine: int = 0
    failed_24h: int = 0
    success_rate_24h: float | None = None  # completed / (completed + failed); None when no run finished


class NeedItem(BaseModel):
    kind: Literal[
        "design_approval", "plan_approval", "question", "escalation", "human_code_review", "draft_answer",
        "needs_human", "mention",
    ]
    ref: str  # task key, or <KEY>-Q<n> for a question between projects
    title: str
    detail: str | None = None
    since: datetime
    link: str
    waiting_for: list[str] = []  # names, under My teams and Everything
    notification_id: uuid.UUID | None = None  # mentions: marked read by Reply


class MyTask(BaseModel):
    key: str
    title: str
    due_date: date
    due: Literal["overdue", "today", "week"]
    link: str


class RunningItem(BaseModel):
    run_id: uuid.UUID
    agent_name: str
    started_at: datetime | None
    task_key: str | None
    stage: Stage | None
    step: int | None
    steps_total: int | None
    review_round: int | None
    question_from: str | None  # answering runs: the asking task's project key
    link: str


class QueuedItem(BaseModel):
    task_key: str | None
    stage: Stage | None
    link: str | None = None


class Queued(BaseModel):
    total: int = 0
    items: list[QueuedItem] = []


class AgentItem(BaseModel):
    id: uuid.UUID
    name: str
    # busy_elsewhere: running only in projects outside the scope (not counted as working here)
    status: Literal["busy", "busy_elsewhere", "online", "offline"]
    runs_today: int


class StageRow(BaseModel):
    stage: Stage
    running: int
    waiting: int
    paused: int  # paused, or idle (manual)


class Stages(BaseModel):
    rows: list[StageRow] = []
    done_30d: int = 0


class DayFinished(BaseModel):
    day: date
    agents: int
    people: int


class ProjectRow(BaseModel):
    key: str
    name: str
    open: int
    in_progress: int
    done: int
    late: int


class ActivityRow(BaseModel):
    id: uuid.UUID
    at: datetime
    kind: str
    data: dict
    actor_name: str | None
    task_key: str
    names: dict[str, str]  # ids in `data` (columns, users, agents) -> names


class SystemOut(BaseModel):
    runners: int
    agents_exist: bool
    jobs_waiting: int
    oldest_job_seconds: int | None
    search_available: bool
    search_documents: int | None
    ai_configured: bool
    ai_jobs_today: int
    ai_failed_today: int
    memory_last_at: datetime | None
    memory_last_failed: bool
    rate_limits_24h: int


class DashboardOut(BaseModel):
    scope: ScopeName
    numbers: Numbers
    needs: list[NeedItem] = []
    my_tasks: list[MyTask] = []
    running: list[RunningItem] = []
    queued: Queued = Queued()
    agents: list[AgentItem] = []
    stages: Stages = Stages()
    finished_daily: list[DayFinished] = []
    projects: list[ProjectRow] = []
    activity: list[ActivityRow] = []
    system: SystemOut | None = None  # admins only


class NeedsCount(BaseModel):
    needs_you: int
