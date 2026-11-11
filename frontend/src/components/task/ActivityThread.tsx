import {
  AlertTriangle,
  CircleCheck,
  CircleX,
  GitCommitHorizontal,
  GitMerge,
  GitPullRequestArrow,
  GitPullRequestClosed,
  MessageSquare,
} from "lucide-react";
import Link from "next/link";

import { ImageGallery } from "@/components/images/ImageGallery";
import { Avatar } from "@/components/ui/Avatar";
import { Markdown } from "@/components/ui/Markdown";
import { QuestionCard } from "@/components/workflow/QuestionCard";
import { ReviewResult } from "@/components/workflow/ReviewFindings";
import { stateText } from "@/lib/agentMessages";
import { joinAgentMessages } from "@/lib/agentReplies";
import { runReasonText } from "@/lib/agents";
import { describeGitEvent, type GitLine } from "@/lib/gitActivity";
import type { ImageRef } from "@/lib/images";
import type { ActivityItem } from "@/lib/types";
import { escalationReasonText, FINISHING_LABEL, STAGES, type FinishingOption } from "@/lib/workflow";

type Names = { columnNames: Map<string, string>; userNames: Map<string, string>; agentNames?: Map<string, string> };

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

const taskHref = (key: string) => `/projects/${key.replace(/-\d+$/, "")}/board?task=${key}`;

function TaskKey({ value }: { value?: string }) {
  if (!value) return <>a task</>;
  return (
    <Link href={taskHref(value)} className="text-cyan-ink underline">
      {value}
    </Link>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "16 – 27 Nov", "30 Nov – 11 Dec", or with the years when they differ; from two YYYY-MM-DD dates. */
export function dateSpan(start?: string, end?: string): string | undefined {
  const parse = (v?: string) => /^(\d{4})-(\d{2})-(\d{2})$/.exec(v ?? "")?.slice(1).map(Number);
  const a = parse(start);
  const b = parse(end);
  if (!a || !b) return undefined;
  const [y1, m1, d1] = a;
  const [y2, m2, d2] = b;
  if (y1 !== y2) return `${d1} ${MONTHS[m1 - 1]} ${y1} – ${d2} ${MONTHS[m2 - 1]} ${y2}`;
  if (m1 !== m2) return `${d1} ${MONTHS[m1 - 1]} – ${d2} ${MONTHS[m2 - 1]}`;
  return `${d1} – ${d2} ${MONTHS[m2 - 1]}`;
}

/** One change a chat's agent made on the board (agent_board_changed), with links to what is still there. */
function boardChange(data: Record<string, unknown>): React.ReactNode {
  const key = str(data.key);
  const project = str(data.project) ?? key?.replace(/-\d+$/, "");
  const sprint = str(data.sprint);
  const sprintLink =
    sprint && project ? (
      <Link href={`/projects/${project}/backlog`} className="text-cyan-ink underline">
        {sprint}
      </Link>
    ) : (
      (sprint ?? "a sprint")
    );
  switch (data.action) {
    case "epic_set": {
      const epic = str(data.epic);
      return epic ? (
        <>
          put <TaskKey value={key} /> under the epic <TaskKey value={epic} />
        </>
      ) : (
        <>
          took <TaskKey value={key} /> out of its epic
        </>
      );
    }
    case "task_changed": {
      const fields = Array.isArray(data.fields) ? data.fields.filter((f): f is string => typeof f === "string") : [];
      return (
        <>
          changed <TaskKey value={key} />
          {fields.length > 0 && `: ${fields.map((f) => f.replace(/_md$/, "").replace(/_/g, " ")).join(", ")}`}
        </>
      );
    }
    case "task_moved":
      return (
        <>
          moved <TaskKey value={key} /> to {str(data.column) ?? "another column"}
        </>
      );
    case "task_deleted":
      return (
        <>
          deleted <s>{key ?? "a task"}</s>
          {str(data.title) ? `: ${str(data.title)}` : ""}
        </>
      );
    case "sprint_created": {
      const span = dateSpan(str(data.start), str(data.end));
      return (
        <>
          created the sprint {sprintLink}
          {span && ` (${span})`}
        </>
      );
    }
    case "sprint_changed":
      return <>changed the sprint {sprintLink}</>;
    case "sprint_started":
      return <>started the sprint {sprintLink}</>;
    case "sprint_completed":
      return <>completed the sprint {sprintLink}</>;
    case "sprint_deleted":
      return <>deleted the sprint {sprint ?? "a sprint"}</>;
    case "sprint_set":
      return sprint ? (
        <>
          added <TaskKey value={key} /> to {sprintLink}
        </>
      ) : (
        <>
          took <TaskKey value={key} /> out of its sprint
        </>
      );
    default:
      return "changed the board";
  }
}

/** " · from the chat <title>": a change a chat's agent made to this task, linked back to that chat. */
function ChatOrigin({ chat }: { chat: unknown }) {
  if (!chat || typeof chat !== "object") return null;
  const id = str((chat as Record<string, unknown>).id);
  const title = str((chat as Record<string, unknown>).title);
  if (!id) return null;
  return (
    <>
      {" · from the chat "}
      <Link href={`/chats/${id}`} className="text-cyan-ink underline">
        {title || "a chat"}
      </Link>
    </>
  );
}

/** Sentence fragment describing an event; unknown kinds (from later features) fall back to the kind itself.
 * `byPerson`: the event has a human actor (e.g. a user cancelled the run). */
export function describeEvent(
  kind: string,
  data: Record<string, unknown>,
  { columnNames, userNames, agentNames }: Names,
  byPerson = false,
): string {
  switch (kind) {
    case "created":
      return "created this task";
    case "status_changed":
      return `moved this to ${columnNames.get(str(data.to_column) ?? "") ?? "another column"}`;
    case "assigned": {
      const to = str(data.to);
      const toAgent = str(data.to_agent);
      if (to) return `assigned this to ${userNames.get(to) ?? "someone"}`;
      if (toAgent) return `assigned this to ${agentNames?.get(toAgent) ?? "an agent"}`;
      return "unassigned this";
    }
    case "field_changed": {
      const field = str(data.field) ?? "a field";
      const label = field.replace(/_md$/, "").replace(/_/g, " ");
      if ("to" in data && data.to !== null && typeof data.to !== "object" && field !== "parent_id") {
        return `changed ${label} to ${String(data.to)}`;
      }
      return `changed ${label}`;
    }
    case "branch_started":
      return `started work from ${str(data.start_branch) ?? "its start branch"}`;
    case "sprint_changed":
      return data.to ? "moved this into a sprint" : "moved this to the backlog";
    case "question_asked":
      if (typeof data.follow_up_of_number === "number") {
        return `asked ${str(data.target_key) ?? "another project"} a follow-up to Q${data.follow_up_of_number} (Q${num(data.number)})`;
      }
      return `asked ${str(data.target_key) ?? "another project"} a question (Q${num(data.number)})`;
    case "question_answered":
      return `${str(data.target_key) ?? "Another project"} answered Q${num(data.number)}`;
    default:
      return describeWorkflowEvent(kind, data) ?? describeAgentEvent(kind, data, byPerson) ?? kind;
  }
}

function num(v: unknown): number {
  return typeof v === "number" ? v : 0;
}

/** Agent-produced fields are shown as plain text only, never as markup (its replies, run summaries and fix summaries
 * render as Markdown in their own box, never as raw HTML). */
function describeAgentEvent(kind: string, data: Record<string, unknown>, byPerson: boolean): string | undefined {
  const reason = str(data.reason);
  switch (kind) {
    case "agent_run_queued":
      return "queued a run";
    case "agent_run_started":
      return "started working";
    case "agent_message":
      return str(data.text) ?? "";
    case "agent_plan": {
      const n = Array.isArray(data.entries) ? data.entries.length : 0;
      return `updated the plan (${n} ${n === 1 ? "step" : "steps"})`;
    }
    case "agent_tool":
      return `${str(data.title) ?? "used a tool"} (${str(data.status) ?? "unknown"})`;
    case "agent_file_change":
      return `changed ${str(data.path) ?? "a file"} (+${num(data.lines_added)} −${num(data.lines_removed)})`;
    case "agent_command":
      return `ran ${str(data.command) ?? "a command"}${data.exit_code == null ? "" : ` → exit ${String(data.exit_code)}`}`;
    case "agent_model": {
      const model = `used the model ${str(data.name) ?? str(data.value) ?? "its default"}`;
      if (!data.effort) return model;
      return data.effort === "default" ? `${model} with its default effort` : `${model} with ${str(data.effort_name) ?? str(data.effort)} effort`;
    }
    case "agent_permission":
      return `was ${data.decision === "allowed" ? "allowed" : "denied"}: ${str(data.title) ?? "a request"}`;
    case "agent_task_created":
      return `created ${str(data.key) ?? "a task"}: ${str(data.title) ?? ""}`;
    case "agent_run_completed":
      // its summary is the agent's last message: the thread shows it as the reply (or under this line, as Markdown)
      return "finished";
    case "agent_run_failed":
      return `failed: ${reason ? runReasonText(reason) : "unknown reason"}`;
    case "agent_run_cancelled":
      if (byPerson) return "cancelled the run";
      return reason ? `was cancelled: ${runReasonText(reason)}` : "was cancelled";
    default:
      return undefined;
  }
}

function stageName(v: unknown): string {
  return STAGES.find((s) => s.id === v)?.label ?? (str(v) ?? "a stage");
}

const PAUSE_REASON: Record<string, string> = { owner_deactivated: "the agent's owner was deactivated" };
const DECISION_TEXT: Record<string, string> = { retry: "chose to retry", accept: "accepted the result", pause: "chose to pause" };
const OUTCOME_TEXT: Record<string, string> = {
  merge_local: "merged locally",
  pull_request: "opened a pull request",
  keep_branch: "kept the branch",
};
const SEVERITY_ORDER = ["critical", "important", "minor"] as const;

function findingTotal(data: Record<string, unknown>): number {
  const counts = (data.counts ?? {}) as Record<string, unknown>;
  return SEVERITY_ORDER.reduce((n, sv) => n + num(counts[sv]), 0);
}

/** Events of the workflow engine, in plain past tense. Agent- and user-written fields are shown as text only. */
function describeWorkflowEvent(kind: string, data: Record<string, unknown>): string | undefined {
  switch (kind) {
    case "workflow.started":
      return "started the workflow";
    case "workflow.paused": {
      const reason = str(data.reason);
      return reason && reason !== "manual"
        ? `paused the workflow (${PAUSE_REASON[reason] ?? reason.replace(/_/g, " ")})`
        : "paused the workflow";
    }
    case "workflow.resumed":
      return "resumed the workflow";
    case "workflow.no_column":
      return `The board has no ${str(data.category) ?? "matching"} column, so the card stayed where it was`;
    case "workflow.stage":
      return `Moved the workflow from ${stageName(data.from)} to ${stageName(data.to)}`;
    case "workflow.escalated":
      return `The workflow needs a decision. ${escalationReasonText(str(data.reason) ?? null)}`;
    case "escalation.decided":
      return DECISION_TEXT[str(data.action) ?? ""] ?? "decided how to continue";
    case "workflow.finished":
      return "The workflow finished";
    case "pr.sent_back": {
      if (data.kind === "merge_conflict") {
        return `Sent back to its agent: merge conflict on PR #${num(data.pr_number)} (round ${num(data.round)} of ${num(data.of)})`;
      }
      const what = data.kind === "fix_comment" ? "/fix" : "changes requested";
      return `Sent back to its agent: ${what} on PR #${num(data.pr_number)} by ${str(data.by) ?? "someone"} (round ${num(data.round)} of ${num(data.of)})`;
    }
    case "pr.fix_pushed":
      return `Fixed and pushed to PR #${num(data.pr_number)} (round ${num(data.round)} of ${num(data.of)})`;
    case "pr.send_back_cancelled":
      return "stopped the fix: back to waiting for the merge";
    case "finishing.changed": {
      const option = str(data.option) as FinishingOption | undefined;
      return option && FINISHING_LABEL[option] ? `set the finishing option to ${FINISHING_LABEL[option]}` : "reset the finishing option";
    }
    case "document.submitted":
      return `submitted ${str(data.kind) ?? "a document"} v${num(data.version)}`;
    case "document.approved":
      return `approved the ${str(data.kind) ?? "document"} v${num(data.version)}`;
    case "document.rejected": {
      const comment = str(data.comment);
      return `rejected the ${str(data.kind) ?? "document"} v${num(data.version)}${comment ? `: ${comment}` : ""}`;
    }
    case "step.completed":
      return `Step ${num(data.step)} completed, ${data.tests_passed ? "tests passed" : "tests not passing"}`;
    case "step.approved":
      return `Step ${num(data.step)} approved`;
    case "mockup.shown":
      return `Mockup v${num(data.version)} shown: ${str(data.title) ?? ""}`;
    case "decision.recorded": {
      const where = typeof data.step === "number" ? `on step ${data.step}` : `during ${stageName(data.stage)}`;
      return `Decision ${where}: ${str(data.decision) ?? ""}`;
    }
    case "step.no_commit":
      return `Step ${num(data.step)} finished without a commit`;
    case "workflow.uncommitted": {
      const who =
        data.role === "final_fix"
          ? "The fix round"
          : data.role === "pr_fix"
            ? "The pull request fix"
            : typeof data.step === "number"
              ? `Step ${data.step}`
              : "The agent's run";
      return `${who} left its changes uncommitted: sent back to its agent to commit them`;
    }
    case "review.result": {
      const counts = (data.counts ?? {}) as Record<string, unknown>;
      const parts = SEVERITY_ORDER.filter((sv) => num(counts[sv]) > 0).map((sv) => `${num(counts[sv])} ${sv}`);
      const what = data.scope === "final" ? "Final review" : `Review of step ${num(data.step)}`;
      const verdict = data.verdict === "approved" ? "approved" : "changes requested";
      return `${what} (round ${num(data.round)}): ${verdict}${parts.length ? ` — ${parts.join(", ")}` : ""}`;
    }
    case "finish.reported": {
      const outcome = OUTCOME_TEXT[str(data.outcome) ?? ""] ?? "finished";
      const branch = str(data.branch);
      return `Finish reported: ${outcome}${branch ? ` on ${branch}` : ""}`;
    }
    case "enforcement.violation":
      return `Enforcement violation during ${stageName(data.stage)}: the repository changed`;
    case "human_review.approved":
      return "approved the pull request";
    default:
      return undefined;
  }
}

/** Events whose text is a full sentence of its own, with no actor in front. */
const STANDALONE = new Set([
  "question_answered",
  "step.completed",
  "step.approved",
  "step.no_commit",
  "workflow.uncommitted",
  "mockup.shown",
  "decision.recorded",
  "review.result",
  "finish.reported",
  "enforcement.violation",
  "workflow.stage",
  "workflow.no_column",
  "workflow.escalated",
  "workflow.finished",
  "pr.sent_back",
  "pr.fix_pushed",
]);

function isSafeUrl(url: string | undefined): url is string {
  return !!url && /^https?:\/\//i.test(url);
}

function when(at: string): string {
  return new Date(at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function ActivityThread({
  items,
  columnNames,
  userNames,
  agentNames,
  hasMore = false,
  onLoadEarlier,
  taskKey = "",
  canAct = false,
  readOnly = false,
  onAnswered,
}: {
  items: ActivityItem[];
  hasMore?: boolean;
  onLoadEarlier?: () => void;
  taskKey?: string;
  /** the viewer may answer questions (workflow.can_act) */
  canAct?: boolean;
  readOnly?: boolean;
  /** an answer was attempted: refetch what the thread shows */
  onAnswered?: () => void;
} & Names) {
  return (
    <>
    {hasMore && onLoadEarlier && (
      <button type="button" className="text-xs text-cyan-ink" onClick={onLoadEarlier}>
        Load earlier activity
      </button>
    )}
    <ol className="space-y-3">
      {withReplies(joinAgentMessages(items)).map(({ item, repliedRun }) => {
        const agentId = str(item.data?.agent_id);
        const isAgent = item.kind?.startsWith("agent_") && !item.actor;
        const actor = item.actor?.name ?? (isAgent ? (agentId && agentNames?.get(agentId)) || "Agent" : "Someone");
        if (item.type === "question" && item.question) {
          return (
            <li key={item.id} id={`activity-${item.id}`} className="flex gap-2">
              <Avatar name="Agent" size={24} />
              <QuestionCard item={item} taskKey={taskKey} canAct={canAct} readOnly={readOnly} onAnswered={onAnswered} />
            </li>
          );
        }
        if (item.type === "comment") {
          const toAgent = item.to_agent;
          return (
            <li key={item.id} id={`activity-${item.id}`} className="flex gap-2">
              <Avatar name={actor} size={24} />
              <div
                data-agent-message={toAgent ? "" : undefined}
                className={`card min-w-0 flex-1 px-3 py-2 ${toAgent ? "border-l-2 border-l-violet" : ""}`}
              >
                <p className="text-xs text-muted-foreground">
                  {toAgent ? (
                    <span className="text-violet">
                      {actor} → {toAgent.agent_name}
                    </span>
                  ) : (
                    <span className="text-fg">{actor}</span>
                  )}
                  {toAgent && <> · {stateText(toAgent)}</>} · {when(item.at)}
                  {item.edited_at && <span className="ml-1">(edited)</span>}
                </p>
                <Markdown>{item.body_md ?? ""}</Markdown>
                <ImageGallery images={item.images ?? []} />
              </div>
            </li>
          );
        }
        const kind = item.kind ?? "";
        const data = item.data ?? {};
        if (kind === "status_changed" && data.by === "workflow") {
          const column = columnNames.get(str(data.to_column) ?? "") ?? "another column";
          return <EventRow key={item.id} at={item.at} text={`Moved to ${column} by the workflow`} />;
        }
        if (kind === "agent_message" && !item.actor) {
          return <AgentReplyRow key={item.id} at={item.at} who={actor} text={str(data.text) ?? ""} />;
        }
        if (kind === "agent_task_created") {
          const key = str(data.key);
          return (
            <EventRow key={item.id} at={item.at} lead={actor} text="created ">
              {key ? (
                <Link href={`/projects/${key.replace(/-\d+$/, "")}/board?task=${key}`} className="text-cyan-ink underline">
                  {key}
                </Link>
              ) : (
                "a task"
              )}
              {`: ${str(data.title) ?? ""}`}
              {data.type === "epic" && <span className="ml-1 rounded border border-violet px-1 text-violet">epic</span>}
            </EventRow>
          );
        }
        if (kind === "agent_board_changed") {
          return (
            <EventRow key={item.id} at={item.at} lead={actor} text="">
              {boardChange(data)}
            </EventRow>
          );
        }
        const git = describeGitEvent(kind, data);
        if (git) return <GitEventRow key={item.id} at={item.at} line={git} />;
        const text = describeEvent(kind, data, { columnNames, userNames, agentNames }, !!item.actor);
        if (kind === "enforcement.violation") return <EventRow key={item.id} at={item.at} text={text} violation />;
        const isWorkflowKind = /^(workflow|escalation|document|step|review|finish|finishing|human_review)[._]/.test(kind);
        const who = item.actor ? actor : kind === "document.submitted" ? "The agent" : isWorkflowKind ? "MegooColab" : actor;
        const docKind = kind.startsWith("document.") && (data.kind === "design" || data.kind === "plan") ? data.kind : undefined;
        const reviewId = kind === "review.result" ? str(data.review_id) : undefined;
        const prUrl = kind === "finish.reported" ? str(data.pr_url) : undefined;
        const fixSummary = kind === "pr.fix_pushed" ? str(data.summary)?.trim() : undefined;
        const runSummary = kind === "agent_run_completed" ? str(data.summary)?.trim() : undefined;
        return (
          <EventRow key={item.id} at={item.at} lead={STANDALONE.has(kind) ? null : who} text={text} docKind={docKind} docVersion={num(data.version)}
            images={item.images}>
            <ChatOrigin chat={data.chat} />
            {isSafeUrl(prUrl) && (
              <>
                {" — "}
                <a href={prUrl} target="_blank" rel="noopener noreferrer" className="text-cyan-ink underline">
                  Open the pull request
                </a>
              </>
            )}
            {reviewId && <ReviewResult taskKey={taskKey} reviewId={reviewId} total={findingTotal(data)} />}
            {fixSummary && (
              <div data-fix-summary className="mt-1 border-l-2 border-line pl-2 text-fg">
                <Markdown compact>{fixSummary}</Markdown>
              </div>
            )}
            {runSummary && !repliedRun(runSummary) && <ReplyBox data-run-summary text={runSummary} />}
          </EventRow>
        );
      })}
    </ol>
    </>
  );
}

function EventRow({
  at,
  text,
  lead = null,
  violation = false,
  docKind,
  docVersion = 0,
  images = [],
  children,
}: {
  at: string;
  text: string;
  lead?: string | null;
  violation?: boolean;
  /** document events link to the design or plan section of the task */
  docKind?: string;
  docVersion?: number;
  /** sent with it: a change request's */
  images?: ImageRef[];
  children?: React.ReactNode;
}) {
  return (
    <li className={`flex items-start gap-2 pl-1 text-xs ${violation ? "text-pink" : "text-muted-foreground"}`}>
      {violation ? (
        <AlertTriangle size={12} aria-hidden className="mt-0.5 shrink-0" />
      ) : (
        <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan" />
      )}
      <span className="min-w-0 break-words">
        {lead && <span className="text-fg">{lead} </span>}
        {docKind ? <DocText text={text} kind={docKind} version={docVersion} /> : text}
        {children}
        <ImageGallery images={images} />
      </span>
      <span className="ml-auto whitespace-nowrap">{when(at)}</span>
    </li>
  );
}

/** What an agent said, as Markdown one size below a design or plan, with a cyan edge marking it as the agent's
 * reply. Raw HTML is never rendered and remote images stay links (Markdown). */
function AgentReplyRow({ at, who, text }: { at: string; who: string; text: string }) {
  return (
    <li data-agent-reply className="flex items-start gap-2 pl-1 text-xs text-muted-foreground">
      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan" />
      <div className="min-w-0 flex-1">
        <span className="text-fg">{who}</span>
        <ReplyBox text={text} />
      </div>
      <span className="ml-auto whitespace-nowrap">{when(at)}</span>
    </li>
  );
}

const GIT_ICON: Record<GitLine["icon"], { Icon: typeof GitMerge; tone: string }> = {
  push: { Icon: GitCommitHorizontal, tone: "text-cyan-ink" },
  opened: { Icon: GitPullRequestArrow, tone: "text-cyan-ink" },
  comment: { Icon: MessageSquare, tone: "text-muted-foreground" },
  approved: { Icon: CircleCheck, tone: "text-green-ink" },
  changes: { Icon: CircleX, tone: "text-pink" },
  reviewed: { Icon: MessageSquare, tone: "text-muted-foreground" },
  "checks-passed": { Icon: CircleCheck, tone: "text-green-ink" },
  "checks-failed": { Icon: CircleX, tone: "text-pink" },
  merged: { Icon: GitMerge, tone: "text-violet" },
  closed: { Icon: GitPullRequestClosed, tone: "text-pink" },
};

/** A pull request or branch event: who (an agent tagged as one), what (linked to the host), the host, and an
 * excerpt quoted as plain text. */
/** An agent's own words, as Markdown in a box with a cyan edge. */
function ReplyBox({ text, ...rest }: { text: string; "data-run-summary"?: boolean }) {
  return (
    <div {...rest} className="mt-1 rounded-r border-l-2 border-cyan bg-surface-2/70 px-3 py-0.5 text-fg">
      <Markdown compact>{text}</Markdown>
    </div>
  );
}

/** Pairs each item with a check of whether a run summary repeats what its run already said in this thread: the
 * runner's summary is a copy of the agent's last message (or its last piece), so a completed run whose reply is
 * shown above it says only that it finished. */
function withReplies(items: ActivityItem[]) {
  const said = new Map<string, string[]>();
  return items.map((item) => {
    const runId = str(item.data?.run_id);
    if (item.kind === "agent_message" && !item.actor && runId) {
      said.set(runId, [...(said.get(runId) ?? []), str(item.data?.text) ?? ""]);
    }
    const replies = runId ? said.get(runId) ?? [] : [];
    return { item, repliedRun: (summary: string) => replies.some((text) => text.includes(summary)) };
  });
}

function GitEventRow({ at, line }: { at: string; line: GitLine }) {
  const { Icon, tone } = GIT_ICON[line.icon];
  return (
    <li className="flex items-start gap-2 pl-1 text-xs text-muted-foreground">
      <Icon size={12} aria-hidden className={`mt-0.5 shrink-0 ${tone}`} />
      <span className="min-w-0 flex-1 break-words">
        {line.lead && (
          <span className="text-fg" title={line.login ? `${line.login}${line.host ? ` on ${line.host}` : ""}` : undefined}>
            {line.lead}
          </span>
        )}
        {line.lead && line.agent && <span className="ml-1 rounded-full border border-violet/50 px-1.5 text-violet">agent</span>}
        {line.lead && " "}
        {line.href ? (
          <a href={line.href} target="_blank" rel="noopener noreferrer" className="text-fg hover:underline">
            {line.text}
          </a>
        ) : (
          line.text
        )}
        {line.host && <span className="ml-1.5 rounded border border-line px-1 text-[0.65rem]">{line.host}</span>}
        {line.detail && <span className="ml-1.5">{line.detail}</span>}
        {(line.quote || line.where) && (
          <span className="mt-1 block border-l-2 border-line pl-2">
            {line.where && <span className="mr-1 font-mono">{line.where}</span>}
            {line.quote}
          </span>
        )}
      </span>
      <span className="ml-auto whitespace-nowrap">{when(at)}</span>
    </li>
  );
}

/** "approved the plan v1": the "plan v1" part links to the document section of the task. */
function DocText({ text, kind, version }: { text: string; kind: string; version: number }) {
  const start = text.indexOf(kind);
  if (start < 0) return <>{text}</>;
  const colon = text.indexOf(":", start);
  const end = colon < 0 ? text.length : colon;
  return (
    <>
      {text.slice(0, start)}
      <a href={`#document-${kind}-v${version}`} className="text-cyan-ink underline">
        {text.slice(start, end)}
      </a>
      {text.slice(end)}
    </>
  );
}
