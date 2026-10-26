import Link from "next/link";

import { kindLabel, type MemChainNode } from "@/lib/memory";

/** The premises a conclusion was derived from, nested to the depth the server sends (5). */
export function ReasoningChain({ nodes }: { nodes: MemChainNode[] }) {
  if (nodes.length === 0) return <p className="text-xs text-muted">Learned directly from its source.</p>;
  return (
    <ul className="space-y-1 border-l border-line pl-3 text-sm">
      {nodes.map((n) => (
        <li key={n.conclusion.id}>
          <span>{n.conclusion.text}</span>{" "}
          <span className="font-mono text-[11px] text-muted">{kindLabel(n.conclusion)}</span>{" "}
          <Link href={`/memory/entity/${n.conclusion.entity_id}`} className="text-xs">
            {n.conclusion.entity_name}
          </Link>
          {n.premises.length > 0 && <ReasoningChain nodes={n.premises} />}
        </li>
      ))}
    </ul>
  );
}
