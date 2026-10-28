import type {
  ActivityRow,
  AgentItem,
  Dashboard,
  DayFinished,
  NeedItem,
  Numbers,
  RunningItem,
  StageRow,
  SystemOut,
} from "@/lib/dashboard";

export const NOW = new Date("2026-10-28T10:12:00Z");

export const numbers: Numbers = {
  need_you: 3, need_you_over_day: 1, agents_working: 1, agents_online: 2, runs_queued: 2, workflows_in_progress: 4,
  workflow_projects: 2, open_tasks: 12, open_in_progress: 5, done_7d: 7, done_prev_7d: 4, overdue: 2, overdue_mine: 1,
  failed_24h: 1, success_rate_24h: 0.75,
};

export function need(kind: NeedItem["kind"], ref: string, title: string, over: Partial<NeedItem> = {}): NeedItem {
  const project = ref.split("-")[0];
  return {
    kind, ref, title, detail: null, since: "2026-10-28T08:12:00Z", link: `/projects/${project}/board?task=${ref}`,
    waiting_for: [], notification_id: null, ...over,
  };
}

export function run(over: Partial<RunningItem> = {}): RunningItem {
  return {
    run_id: "r1", agent_name: "Vera's Claude Code", started_at: "2026-10-28T10:00:00Z", task_key: "PAY-14",
    stage: "build", step: 2, steps_total: 3, review_round: null, question_from: null,
    link: "/projects/PAY/board?task=PAY-14", ...over,
  };
}

export function agent(over: Partial<AgentItem> = {}): AgentItem {
  return { id: "a1", name: "Vera's Claude Code", status: "busy", runs_today: 9, ...over };
}

export function stageRow(stage: StageRow["stage"], running = 0, waiting = 0, paused = 0): StageRow {
  return { stage, running, waiting, paused };
}

export function fourteenDays(last: { agents: number; people: number } = { agents: 2, people: 1 }): DayFinished[] {
  return Array.from({ length: 14 }, (_, i) => {
    const day = new Date(Date.UTC(2026, 9, 15 + i)).toISOString().slice(0, 10);
    return i === 13 ? { day, ...last } : { day, agents: 0, people: 0 };
  });
}

export const healthy: SystemOut = {
  runners: 2, agents_exist: true, jobs_waiting: 0, oldest_job_seconds: null, search_available: true,
  search_documents: 120, ai_configured: true, ai_jobs_today: 12, ai_failed_today: 0,
  memory_last_at: "2026-10-28T02:00:00Z", memory_last_failed: false, rate_limits_24h: 0,
};

export const act: ActivityRow = {
  id: "e1", at: "2026-10-28T10:00:00Z", kind: "created", data: {}, actor_name: "Ana", task_key: "PAY-3", names: {},
};

export function dashboardFixture(over: Partial<Dashboard> = {}): Dashboard {
  return {
    scope: "teams",
    numbers,
    needs: [need("design_approval", "PAY-12", "Refund flow for partial orders")],
    my_tasks: [{ key: "PAY-11", title: "Talk to finance", due_date: "2026-10-28", due: "today", link: "/projects/PAY/board?task=PAY-11" }],
    running: [run()],
    queued: { total: 0, items: [] },
    agents: [agent()],
    stages: { rows: ["brainstorm", "design", "plan", "build", "review", "done"].map((s) => stageRow(s as StageRow["stage"])), done_30d: 0 },
    finished_daily: fourteenDays(),
    projects: [{ key: "PAY", name: "Payments", open: 4, in_progress: 2, done: 6, late: 1 }],
    activity: [act],
    system: null,
    ...over,
  };
}
