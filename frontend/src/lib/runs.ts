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
