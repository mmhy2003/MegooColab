export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export function Avatar({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <span
      title={name}
      aria-label={name}
      className="inline-grid shrink-0 place-items-center rounded-sm bg-pink font-display font-bold text-on-accent"
      style={{ width: size, height: size, fontSize: Math.max(8, size * 0.42) }}
    >
      {initials(name)}
    </span>
  );
}
