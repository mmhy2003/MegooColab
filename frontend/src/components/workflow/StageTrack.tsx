import { STAGES, stageIndex, stageLabel } from "@/lib/workflow";
import type { WorkflowStage, WorkflowStatus } from "@/lib/types";

const STATUS_TEXT: Record<WorkflowStatus, string> = {
  idle: "not started",
  running: "running",
  waiting_human: "",
  paused: "paused",
  finished: "finished",
};

/** Six segments: completed stages in a softer fill, the current one glowing cyan (pink with an outline while a
 *  human is needed). Colour and animation are never the only signal: the label carries "n of 6" and the status
 *  is written out ("running", "paused", "waiting for you" or "waiting on a person"). */
export function StageTrack({
  stage,
  status,
  canAct = false,
  compact = false,
  hideStatus = false,
}: {
  stage: WorkflowStage;
  status: WorkflowStatus;
  canAct?: boolean;
  compact?: boolean;
  /** the caller already prints the status (full size only) */
  hideStatus?: boolean;
}) {
  const current = stageIndex(stage);
  const waiting = status === "waiting_human";
  const finished = status === "finished";
  const label = `Stage: ${stageLabel(stage)} (${current + 1} of ${STAGES.length})`;
  const statusText = waiting ? (canAct ? "waiting for you" : "waiting on a person") : STATUS_TEXT[status];
  return (
    <div role="group" aria-label={label} className="space-y-1">
      <div className={`flex ${compact ? "gap-0.5" : "gap-1"}`}>
        {STAGES.map((s, i) => {
          const done = finished || i < current;
          const isCurrent = !finished && i === current;
          let cls = "border border-line bg-surface-2";
          if (done) cls = "border border-cyan-ink bg-cyan-ink/50";
          else if (isCurrent && waiting) cls = "border-2 border-pink bg-pink glow-box-pink";
          else if (isCurrent) cls = `border border-cyan bg-cyan glow-box ${status === "running" ? "motion-safe:animate-pulse" : ""}`;
          return (
            <span
              key={s.id}
              data-stage={s.id}
              data-state={done ? "done" : isCurrent ? "current" : "todo"}
              className={`${compact ? "h-1.5" : "h-2.5"} flex-1 rounded-sm ${cls}`}
            />
          );
        })}
      </div>
      {!compact && (
        <div className="flex gap-1 text-[11px] text-muted-foreground">
          {STAGES.map((s) => (
            <span key={s.id} className={`flex-1 truncate ${s.id === stage ? "font-semibold text-fg" : ""}`}>
              {s.label}
            </span>
          ))}
        </div>
      )}
      {!(hideStatus && !compact) && (
      <p className="text-[11px] text-muted-foreground">
        {compact ? (
          <>
            {stageLabel(stage)}
            {statusText && <span className={waiting && canAct ? "text-pink" : undefined}> · {statusText}</span>}
          </>
        ) : (
          statusText && (
            <span className={waiting && canAct ? "text-pink" : undefined}>
              {statusText[0].toUpperCase() + statusText.slice(1)}
            </span>
          )
        )}
      </p>
      )}
    </div>
  );
}
