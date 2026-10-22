export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Decorative by default (shown next to the name); pass `labelled` when it stands alone. */
export function Avatar({ name, size = 20, labelled = false }: { name: string; size?: number; labelled?: boolean }) {
  return (
    <span
      title={name}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? name : undefined}
      aria-hidden={labelled ? undefined : true}
      className="inline-grid shrink-0 place-items-center rounded-sm bg-pink font-display font-bold text-on-accent"
      style={{ width: size, height: size, fontSize: Math.max(8, size * 0.42) }}
    >
      {initials(name)}
    </span>
  );
}
