"use client";

import { KbMarkdown } from "@/components/kb/KbMarkdown";
import { Button } from "@/components/ui/Button";
import type { DraftSegment, DraftTarget } from "@/lib/kbDrafts";
import { wordDiff } from "@/lib/wordDiff";

const MARK_STYLE = {
  added: "border-green bg-green/5",
  changed: "border-amber bg-amber/5",
  removed: "border-pink bg-pink/5",
} as const;

const HEADING = /^#{1,6}\s+(.+?)\s*#*\s*$/;
const TARGET_TEXT_MAX = 2000;

/** The section a block falls under: the last heading at or before it, or "Top". */
function sectionOf(segments: DraftSegment[], upTo: number, inside: string): string {
  const text = [...segments.slice(0, upTo).map((s) => (s.kind === "mark" ? s.new_md : s.md) ?? ""), inside].join("\n");
  const headings = text.split("\n").map((l) => HEADING.exec(l)?.[1]).filter(Boolean);
  return headings[headings.length - 1] ?? "Top";
}

/** The draft as it will look, with the last turn's changes marked for keeping or undoing. Selecting text aims the
 * next request at it. */
export function DraftView({
  segments,
  busy,
  onMark,
  onTarget,
}: {
  segments: DraftSegment[];
  busy: boolean;
  onMark: (id: number, to: "keep" | "undo") => void;
  onTarget: (target: DraftTarget) => void;
}) {
  const pick = (e: React.MouseEvent<HTMLElement>) => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";
    if (!text) return;
    const node = selection?.anchorNode;
    const el = (node instanceof Element ? node : node?.parentElement)?.closest<HTMLElement>("[data-seg]");
    const index = Number(el?.dataset.seg ?? e.currentTarget.dataset.seg ?? 0);
    const seg = segments[index];
    // the heading of the selected text: within its block, up to where the selection is
    const own = (seg?.kind === "mark" ? seg.new_md : seg?.md) ?? "";
    const before = own.slice(0, Math.max(0, own.indexOf(text.split("\n")[0])));
    onTarget({ section: sectionOf(segments, index, before), text: text.slice(0, TARGET_TEXT_MAX) });
  };

  if (segments.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing written yet.</p>;
  }
  return (
    <div className="space-y-3">
      {segments.map((s, i) =>
        s.kind === "text" ? (
          <div key={i} data-seg={i} className="kb-prose" onMouseUp={pick}>
            <KbMarkdown>{s.md ?? ""}</KbMarkdown>
          </div>
        ) : (
          <section
            key={i}
            data-seg={i}
            aria-label={`${s.change} by the agent`}
            className={`rounded-r border-l-4 px-3 py-2 ${MARK_STYLE[s.change ?? "added"]}`}
            onMouseUp={pick}
          >
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded border border-violet px-1 text-violet">{s.change}</span>
              <span className="min-w-0 truncate">“{s.request}”</span>
              <span className="ml-auto flex gap-2">
                <Button variant="ghost" className="min-h-8" disabled={busy} onClick={() => onMark(s.id ?? 0, "keep")}>
                  Keep
                </Button>
                <Button variant="ghost" className="min-h-8" disabled={busy} onClick={() => onMark(s.id ?? 0, "undo")}>
                  Undo
                </Button>
              </span>
            </div>
            {s.change === "added" && (
              <div className="kb-prose">
                <KbMarkdown>{s.new_md ?? ""}</KbMarkdown>
              </div>
            )}
            {s.change === "removed" && (
              <div className="kb-prose text-pink line-through opacity-80">
                <KbMarkdown>{s.old_md ?? ""}</KbMarkdown>
              </div>
            )}
            {s.change === "changed" && (
              <p className="text-sm break-words whitespace-pre-wrap">
                {wordDiff(s.old_md ?? "", s.new_md ?? "").map((w, k) =>
                  w.op === "same" ? (
                    <span key={k}>{w.text}</span>
                  ) : w.op === "del" ? (
                    <del key={k} className="text-pink">
                      {w.text}
                    </del>
                  ) : (
                    <ins key={k} className="text-green-ink no-underline">
                      {w.text}
                    </ins>
                  ),
                )}
              </p>
            )}
          </section>
        ),
      )}
    </div>
  );
}
