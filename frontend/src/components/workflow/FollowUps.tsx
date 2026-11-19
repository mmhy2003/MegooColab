"use client";

import Link from "next/link";

import { Button } from "@/components/ui/Button";
import type { DocumentDetail, FollowUpRef } from "@/lib/types";

export type FollowUpType = "story" | "task" | "bug";
export type FollowUpRow = { title: string; type: FollowUpType; description_md: string; create: boolean; added: boolean };
export const MAX_FOLLOW_UPS = 10;

const TYPES: FollowUpType[] = ["story", "task", "bug"];
const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm";

/** The rows a review starts from: every proposed entry, ticked. */
export function initialRows(detail: DocumentDetail): FollowUpRow[] {
  return detail.follow_ups.map((f) => ({
    title: f.title,
    type: (TYPES as string[]).includes(f.type) ? (f.type as FollowUpType) : "task",
    description_md: f.description_md,
    create: true,
    added: false,
  }));
}

function TaskLink({ projectKey, taskKey }: { projectKey: string; taskKey: string }) {
  return (
    <Link href={`/projects/${projectKey}/board?task=${taskKey}`} className="text-cyan-ink underline">
      {taskKey}
    </Link>
  );
}

function Earlier({ refs, projectKey }: { refs: FollowUpRef[]; projectKey: string }) {
  if (!refs.length) return null;
  return (
    <p className="text-xs text-muted-foreground">
      Already created from an earlier approved design:{" "}
      {refs.map((r, i) => (
        <span key={r.key}>
          {i > 0 && ", "}
          <TaskLink projectKey={projectKey} taskKey={r.key} />
        </span>
      ))}
      .
    </p>
  );
}

/**
 * The "Follow-up tasks" block of a design: the tasks it proposes for later phases (MC-81). With `review`, the person
 * can untick, edit, add and remove rows before approving; without it, the list is shown as text, and on an approved
 * version each entry says whether it was created.
 */
export function FollowUps({
  detail,
  projectKey,
  review,
}: {
  detail: DocumentDetail;
  projectKey: string;
  review?: { rows: FollowUpRow[]; onChange: (rows: FollowUpRow[]) => void };
}) {
  const earlier = detail.earlier_follow_ups;
  if (!review && !detail.follow_ups.length && !earlier.length) return null;

  const heading = <h3 className="font-semibold">Follow-up tasks</h3>;

  if (!review) {
    const approved = detail.status === "approved";
    return (
      <section aria-label="Follow-up tasks" className="space-y-1.5">
        {heading}
        <Earlier refs={earlier} projectKey={projectKey} />
        {detail.follow_ups.length > 0 && (
          <ul className="ml-5 list-disc space-y-1">
            {detail.follow_ups.map((f, i) => (
              <li key={i}>
                <span>
                  {f.type} · {f.title}
                </span>
                {approved && (
                  <span className="text-xs text-muted-foreground">
                    {" · "}
                    {f.created ? (
                      f.task_key ? (
                        <>
                          created <TaskLink projectKey={projectKey} taskKey={f.task_key} />
                        </>
                      ) : (
                        "created"
                      )
                    ) : (
                      "not created"
                    )}
                  </span>
                )}
                {f.description_md && (
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">Description</summary>
                    <p className="whitespace-pre-wrap">{f.description_md}</p>
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  const { rows, onChange } = review;
  const update = (i: number, patch: Partial<FollowUpRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <section aria-label="Follow-up tasks" className="space-y-1.5">
      {heading}
      <Earlier refs={earlier} projectKey={projectKey} />
      {rows.length === 0 && <p className="text-xs text-muted-foreground">None proposed.</p>}
      {rows.length > 0 && (
        <ol className="space-y-2">
          {rows.map((r, i) => {
            const n = i + 1;
            return (
              <li key={i} className="space-y-1">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label={`Create task ${n}`}
                    checked={r.create}
                    onChange={(e) => update(i, { create: e.target.checked })}
                  />
                  <select
                    aria-label={`Type of task ${n}`}
                    className={`${FIELD} w-auto`}
                    value={r.type}
                    onChange={(e) => update(i, { type: e.target.value as FollowUpType })}
                  >
                    {TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={`Title of task ${n}`}
                    maxLength={500}
                    className={FIELD}
                    value={r.title}
                    onChange={(e) => update(i, { title: e.target.value })}
                  />
                  {r.added && (
                    <>
                      <span className="shrink-0 text-xs text-muted-foreground">added by you</span>
                      <button
                        type="button"
                        aria-label={`Remove task ${n}`}
                        className="shrink-0 text-xs text-pink hover:underline"
                        onClick={() => onChange(rows.filter((_, j) => j !== i))}
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Description</summary>
                  <textarea
                    aria-label={`Description of task ${n}`}
                    rows={3}
                    maxLength={4000}
                    className={FIELD}
                    value={r.description_md}
                    onChange={(e) => update(i, { description_md: e.target.value })}
                  />
                </details>
              </li>
            );
          })}
        </ol>
      )}
      <Button
        variant="ghost"
        disabled={rows.length >= MAX_FOLLOW_UPS}
        onClick={() => onChange([...rows, { title: "", type: "task", description_md: "", create: true, added: true }])}
      >
        + Add a task
      </Button>
    </section>
  );
}
