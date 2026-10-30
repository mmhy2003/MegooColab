/** Finding Mermaid diagrams quoted inside a Markdown code block. Plain functions, so Markdown can use them on the
 * server too (MermaidDiagram itself is a client component). */

// a diagram longer than this is shown as code: drawing it could freeze the page
export const MAX_DIAGRAM_CHARS = 20_000;

export type MermaidSegment = { kind: "code"; text: string } | { kind: "diagram"; source: string };

const OPEN = /^( *)(`{3,}|~{3,})[ \t]*mermaid\b[^`]*$/;
const CLOSE = /^ *(`{3,}|~{3,})[ \t]*$/;

function trimBlankLines(lines: string[]): string {
  let start = 0;
  let end = lines.length;
  while (start < end && !lines[start].trim()) start++;
  while (end > start && !lines[end - 1].trim()) end--;
  return lines.slice(start, end).join("\n");
}

/** A code block's text cut into the ```mermaid fences quoted inside it and the text around them. A fence that
 * never closes, and everything after it, stays text. */
export function splitMermaid(text: string): MermaidSegment[] {
  const lines = text.split("\n");
  const out: MermaidSegment[] = [];
  let pending: string[] = [];
  const flush = () => {
    const code = trimBlankLines(pending);
    if (code) out.push({ kind: "code", text: code });
    pending = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const open = OPEN.exec(lines[i]);
    if (!open) {
      pending.push(lines[i]);
      continue;
    }
    const [, indent, fence] = open;
    let close = -1;
    for (let j = i + 1; j < lines.length; j++) {
      const m = CLOSE.exec(lines[j]);
      if (m && m[1][0] === fence[0] && m[1].length >= fence.length) {
        close = j;
        break;
      }
    }
    if (close < 0) {
      pending.push(...lines.slice(i));
      break;
    }
    flush();
    const body = lines.slice(i + 1, close).map((l) => (l.startsWith(indent) ? l.slice(indent.length) : l.trimStart()));
    out.push({ kind: "diagram", source: trimBlankLines(body) });
    i = close;
  }
  flush();
  return out;
}
