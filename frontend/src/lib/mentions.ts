import { agentMentionToken } from "@/lib/agentMessages";
import { mentionToken } from "@/lib/notifications";

/** Someone picked from the comment box's @ list: the box shows `@Name`, and the token is written only on sending. */
export type PickedMention = { id: string; name: string; agent?: boolean };
export type MentionRange = { start: number; end: number; mention: PickedMention };

// a mention starts the text or follows a space or an opening bracket, and no letter or digit runs on after the name
const BEFORE = /[\s([{]/;
const AFTER = /[\p{L}\p{N}_]/u;

/** Where the picked names stand in the text as `@Name`, in order; longer names win where two would overlap. */
export function mentionRanges(text: string, picked: PickedMention[]): MentionRange[] {
  const found: MentionRange[] = [];
  const byLength = [...picked].sort((a, b) => b.name.length - a.name.length);
  for (const mention of byLength) {
    const at = `@${mention.name}`;
    for (let i = text.indexOf(at); i !== -1; i = text.indexOf(at, i + 1)) {
      const end = i + at.length;
      if (i > 0 && !BEFORE.test(text[i - 1])) continue;
      if (end < text.length && AFTER.test(text[end])) continue;
      if (found.some((r) => i < r.end && end > r.start)) continue;
      found.push({ start: i, end, mention });
    }
  }
  return found.sort((a, b) => a.start - b.start);
}

/** The text as it is sent: each `@Name` becomes its mention token. */
export function encodeMentions(text: string, picked: PickedMention[]): string {
  let out = "";
  let from = 0;
  for (const r of mentionRanges(text, picked)) {
    out += text.slice(from, r.start) + (r.mention.agent ? agentMentionToken(r.mention) : mentionToken(r.mention));
    from = r.end;
  }
  return out + text.slice(from);
}

/** The mention that ends exactly at the caret, which Backspace removes whole. */
export function mentionAt(text: string, picked: PickedMention[], caret: number): MentionRange | null {
  return mentionRanges(text, picked).find((r) => r.end === caret) ?? null;
}
