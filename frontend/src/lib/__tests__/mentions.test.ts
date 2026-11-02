import { describe, expect, it } from "vitest";

import { encodeMentions, mentionAt, mentionRanges, type PickedMention } from "@/lib/mentions";

const MO: PickedMention = { id: "11111111-1111-4111-8111-111111111111", name: "Mohamed Youssef" };
const MOHA: PickedMention = { id: "22222222-2222-4222-8222-222222222222", name: "Moha" };
const AGENT: PickedMention = { id: "a1", name: "Claude Code - Legion", agent: true };

describe("mentions in the comment box", () => {
  it("finds each picked name written as @Name, longest first", () => {
    const text = "@Mohamed Youssef and @Moha, ask @Claude Code - Legion.";
    expect(mentionRanges(text, [MOHA, MO, AGENT]).map((r) => text.slice(r.start, r.end))).toEqual([
      "@Mohamed Youssef", "@Moha", "@Claude Code - Legion",
    ]);
  });

  it("a name cut short or run into a word is plain text", () => {
    expect(mentionRanges("@Mohamed Yous and @Mohamed Youssefx", [MO])).toEqual([]);
    expect(mentionRanges("mail@Mohamed Youssef", [MO])).toEqual([]);
  });

  it("encodes each mention as its token when sent", () => {
    expect(encodeMentions("Hi @Mohamed Youssef, @Claude Code - Legion please wait", [MO, AGENT])).toBe(
      `Hi @[Mohamed Youssef](user:${MO.id}), @[Claude Code - Legion](agent:a1) please wait`,
    );
  });

  it("leaves a token typed or pasted by hand as it is", () => {
    const raw = `@[Mohamed Youssef](user:${MO.id}) hi`;
    expect(encodeMentions(raw, [MO])).toBe(raw);
  });

  it("knows the mention the caret sits right after", () => {
    const text = "Hi @Moha there";
    expect(mentionAt(text, [MOHA], 8)).toEqual({ start: 3, end: 8, mention: MOHA });
    expect(mentionAt(text, [MOHA], 9)).toBeNull();
  });
});
