import { AlertTriangle } from "lucide-react";

import { Avatar } from "@/components/ui/Avatar";
import { Markdown } from "@/components/ui/Markdown";
import { QuestionCard } from "@/components/workflow/QuestionCard";
import { ReviewResult } from "@/components/workflow/ReviewFindings";
import { runReasonText } from "@/lib/agents";
import type { ActivityItem } from "@/lib/types";
import { escalationReasonText, FINISHING_LABEL, STAGES, type FinishingOption } from "@/lib/workflow";

type Names = { columnNames: Map<string, string>; userNames: Map<string, string>; agentNames?: Map<string, string> };

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
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

/** Agent-produced fields are shown as plain text only, never as markup. */
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
    case "agent_permission":
      return `was ${data.decision === "allowed" ? "allowed" : "denied"}: ${str(data.title) ?? "a request"}`;
    case "agent_run_completed":
      return `finished: ${str(data.summary) ?? "done"}`;
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
  "mockup.shown",
  "decision.recorded",
  "review.result",
  "finish.reported",
  "enforcement.violation",
  "workflow.stage",
  "workflow.no_column",
  "workflow.escalated",
  "workflow.finished",
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
      {items.map((item) => {
        const agentId = str(item.data?.agent_id);
        const isAgent = item.kind?.startsWith("agent_") && !item.actor;
        const actor = item.actor?.name ?? (isAgent ? (agentId && agentNames?.get(agentId)) || "Agent" : "Someone");
        if (item.type === "question" && item.question) {
          return (
            <li key={item.id} className="flex gap-2">
              <Avatar name="Agent" size={24} />
              <QuestionCard item={item} taskKey={taskKey} canAct={canAct} readOnly={readOnly} onAnswered={onAnswered} />
            </li>
          );
        }
        if (item.type === "comment") {
          return (
            <li key={item.id} className="flex gap-2">
              <Avatar name={actor} size={24} />
              <div className="card min-w-0 flex-1 px-3 py-2">
                <p className="text-xs text-muted-foreground">
                  <span className="text-fg">{actor}</span> · {when(item.at)}
                  {item.edited_at && <span className="ml-1">(edited)</span>}
                </p>
                <Markdown>{item.body_md ?? ""}</Markdown>
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
        const text = describeEvent(kind, data, { columnNames, userNames, agentNames }, !!item.actor);
        if (kind === "enforcement.violation") return <EventRow key={item.id} at={item.at} text={text} violation />;
        const isWorkflowKind = /^(workflow|escalation|document|step|review|finish|finishing|human_review)[._]/.test(kind);
        const who = item.actor ? actor : kind === "document.submitted" ? "The agent" : isWorkflowKind ? "MegooColab" : actor;
        const docKind = kind.startsWith("document.") && (data.kind === "design" || data.kind === "plan") ? data.kind : undefined;
        const reviewId = kind === "review.result" ? str(data.review_id) : undefined;
        const prUrl = kind === "finish.reported" ? str(data.pr_url) : undefined;
        return (
          <EventRow key={item.id} at={item.at} lead={STANDALONE.has(kind) ? null : who} text={text} docKind={docKind} docVersion={num(data.version)}>
            {isSafeUrl(prUrl) && (
              <>
                {" — "}
                <a href={prUrl} target="_blank" rel="noopener noreferrer" className="text-cyan-ink underline">
                  Open the pull request
                </a>
              </>
            )}
            {reviewId && <ReviewResult taskKey={taskKey} reviewId={reviewId} total={findingTotal(data)} />}
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
  children,
}: {
  at: string;
  text: string;
  lead?: string | null;
  violation?: boolean;
  /** document events link to the design or plan section of the task */
  docKind?: string;
  docVersion?: number;
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
