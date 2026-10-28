type Tone = "cyan" | "pink" | "green" | "muted" | "amber";

const TONES: Record<Tone, string> = {
  cyan: "border-cyan text-cyan-ink",
  pink: "border-pink text-pink",
  green: "border-green text-green-ink",
  amber: "border-amber text-amber",
  muted: "border-line text-muted-foreground",
};

export function Badge({
  tone = "muted",
  children,
  className = "",
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] leading-none uppercase ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
