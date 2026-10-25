import { STAGES, stageIndex, stageLabel } from "@/lib/workflow";
import type { WorkflowStage, WorkflowStatus } from "@/lib/types";

/** Six segments: completed stages filled, the current one glowing cyan (pink with an outline while a human is needed).
 *  Colour is never the only signal: the label carries "n of 6", and the waiting state adds an outline and "waiting". */
export function StageTrack({
  stage,
  status,
  compact = false,
}: {
  stage: WorkflowStage;
  status: WorkflowStatus;
  compact?: boolean;
}) {
  const current = stageIndex(stage);
  const waiting = status === "waiting_human";
  const finished = status === "finished";
  const label = `Stage: ${stageLabel(stage)} (${current + 1} of ${STAGES.length})`;
  return (
    <div role="group" aria-label={label} className="space-y-1">
      <div className={`flex ${compact ? "gap-0.5" : "gap-1"}`}>
        {STAGES.map((s, i) => {
          const done = finished || i < current;
          const isCurrent = !finished && i === current;
          let cls = "border border-line bg-surface-2";
          if (done) cls = "border border-cyan-ink bg-cyan-ink";
          else if (isCurrent && waiting) cls = "border-2 border-pink bg-pink glow-box";
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
        <div className="flex gap-1 text-[11px] text-muted">
          {STAGES.map((s) => (
            <span key={s.id} className={`flex-1 truncate ${s.id === stage ? "font-semibold text-fg" : ""}`}>
              {s.label}
            </span>
          ))}
        </div>
      )}
      {compact ? (
        <p className="text-[11px] text-muted">
          {stageLabel(stage)}
          {waiting && <span className="text-pink"> · waiting for you</span>}
        </p>
      ) : (
        waiting && <p className="text-[11px] text-pink">Waiting for you</p>
      )}
    </div>
  );
}
