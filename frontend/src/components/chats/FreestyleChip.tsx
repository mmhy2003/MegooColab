/** Marks a freestyle chat, where a workflow chat shows its progress (the chat's header, its row in the list). */
export function FreestyleChip({ className = "" }: { className?: string }) {
  return <span className={`rounded border border-violet px-1.5 text-xs text-violet ${className}`}>Freestyle</span>;
}
