import type { DiffOp } from "@/lib/kb";

type Line = { kind: "equal" | "insert" | "delete"; text: string; n: number };

const MARK = { equal: " ", insert: "+", delete: "−" } as const;
const LABEL = { equal: "Unchanged line", insert: "Added line", delete: "Removed line" } as const;
const STYLE = {
  equal: "text-muted",
  insert: "bg-green/10 text-green-ink",
  delete: "bg-pink/10 text-pink line-through decoration-pink/40",
} as const;

function lines(op: Exclude<DiffOp, { op: "collapsed" }>): Line[] {
  if (op.op === "equal") return op.b_lines.map((text, i) => ({ kind: "equal", text, n: op.b_start + i }));
  const removed = op.a_lines.map((text, i): Line => ({ kind: "delete", text, n: op.a_start + i }));
  const added = op.b_lines.map((text, i): Line => ({ kind: "insert", text, n: op.b_start + i }));
  return [...removed, ...added];
}

/** A line diff between two revisions. Changes are marked with + and − as well as colour. */
export function DiffView({ ops }: { ops: DiffOp[] }) {
  return (
    <div className="overflow-x-auto rounded border border-line font-mono text-xs" role="list" aria-label="Changes">
      {ops.map((op, i) =>
        op.op === "collapsed" ? (
          <div key={i} role="listitem" className="bg-surface-2 px-3 py-1 text-center text-muted">
            {op.count} unchanged lines
          </div>
        ) : (
          lines(op).map((l, j) => (
            <div
              key={`${i}-${j}`}
              role="listitem"
              data-op={l.kind}
              aria-label={`${LABEL[l.kind]} ${l.n}`}
              className={`flex gap-2 px-2 whitespace-pre-wrap ${STYLE[l.kind]}`}
            >
              <span aria-hidden className="w-10 shrink-0 text-right text-muted select-none">
                {l.n}
              </span>
              <span aria-hidden className="w-3 shrink-0 select-none">
                {MARK[l.kind]}
              </span>
              <span className="min-w-0 break-words">{l.text || " "}</span>
            </div>
          ))
        ),
      )}
    </div>
  );
}
