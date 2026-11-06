import type { ActivityItem } from "@/lib/types";

/** The runner sends an agent's reply in pieces every few seconds, each an `agent_message` event: neighbouring pieces
 * of the same run are one reply, joined back together (in order, with nothing between them) so it reads, and
 * renders as Markdown, as one message. Anything else in between ends the reply. */
export function joinAgentMessages(items: ActivityItem[]): ActivityItem[] {
  const out: ActivityItem[] = [];
  for (const item of items) {
    const prev = out[out.length - 1];
    if (isPiece(item) && prev && isPiece(prev) && prev.data?.run_id === item.data?.run_id) {
      const text = `${String(prev.data?.text ?? "")}${String(item.data?.text ?? "")}`;
      out[out.length - 1] = { ...prev, data: { ...prev.data, text } };
      continue;
    }
    out.push(item);
  }
  return out;
}

function isPiece(item: ActivityItem): boolean {
  return item.type === "event" && item.kind === "agent_message" && !item.actor && typeof item.data?.run_id === "string";
}
