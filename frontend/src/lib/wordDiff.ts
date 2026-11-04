export type WordOp = { op: "same" | "del" | "add"; text: string };

/** Past this many token pairs a word-by-word comparison costs too much: the whole text is shown replaced. */
const MAX_CELLS = 40_000;

const tokens = (text: string) => text.match(/\s+|\S+/g) ?? [];

/** What changed between two texts, word by word: the words that stayed, went and came, with their spaces. The space
 * between two changed words belongs to the change, so "this part" → "that bit" reads as one replacement. */
export function wordDiff(a: string, b: string): WordOp[] {
  const x = tokens(a);
  const y = tokens(b);
  if (x.length * y.length > MAX_CELLS) return [...(a ? [{ op: "del" as const, text: a }] : []), ...(b ? [{ op: "add" as const, text: b }] : [])];
  // longest common subsequence, filled from the end so the walk below goes forwards
  const lcs = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const raw: WordOp[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) {
      raw.push({ op: "same", text: x[i++] });
      j++;
    } else if (j < y.length && (i === x.length || lcs[i][j + 1] >= lcs[i + 1][j])) {
      raw.push({ op: "add", text: y[j++] });
    } else {
      raw.push({ op: "del", text: x[i++] });
    }
  }
  const out: WordOp[] = [];
  let del = "";
  let add = "";
  const flush = () => {
    if (del) out.push({ op: "del", text: del });
    if (add) out.push({ op: "add", text: add });
    del = add = "";
  };
  raw.forEach((t, k) => {
    if (t.op === "del") del += t.text;
    else if (t.op === "add") add += t.text;
    else if ((del || add) && !t.text.trim() && raw[k + 1] && raw[k + 1].op !== "same") {
      del += t.text; // a space between two changed words
      add += t.text;
    } else {
      flush();
      const last = out[out.length - 1];
      if (last?.op === "same") last.text += t.text;
      else out.push({ op: "same", text: t.text });
    }
  });
  flush();
  return out;
}
