import type { LucideIcon } from "lucide-react";
import Link from "next/link";

/** A dashboard card: an uppercase heading with its icon, an optional count and "→" link, then the content. While
 * loading it keeps its frame with a muted placeholder, so the page does not jump when the data arrives. */
export function Widget({
  title,
  icon: Icon,
  more,
  count,
  loading = false,
  tag,
  className = "",
  children,
}: {
  title: string;
  icon: LucideIcon;
  more?: { href: string; label: string };
  count?: number;
  loading?: boolean;
  tag?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section aria-label={title} className={`card min-w-0 px-3.5 py-3 ${className}`}>
      <h2 className="mb-2 flex items-center gap-1.5 text-xs tracking-widest text-muted-foreground uppercase">
        <Icon size={14} aria-hidden className="shrink-0" />
        <span className="truncate">{title}</span>
        {!!count && (
          <span className="rounded-full bg-pink px-1.5 font-mono text-[11px] leading-4 tracking-normal text-on-accent">{count}</span>
        )}
        {tag && <span className="text-[10px] text-amber">{tag}</span>}
        {more && (
          <Link href={more.href} className="ml-auto shrink-0 tracking-normal text-cyan-ink normal-case no-underline hover:underline">
            {more.label} →
          </Link>
        )}
      </h2>
      {loading ? <div aria-hidden className="h-24 animate-pulse rounded bg-surface-2" /> : children}
    </section>
  );
}

/** The one muted line an empty widget shows. */
export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-2 text-sm text-muted-foreground">{children}</p>;
}

/** A small outlined label, coloured by meaning. */
export function Chip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`shrink-0 rounded-sm border border-current px-1.5 text-[11px] whitespace-nowrap ${TONES[tone]}`}>{children}</span>;
}

export type Tone = "pink" | "amber" | "cyan" | "green" | "violet" | "muted";

export const TONES: Record<Tone, string> = {
  pink: "text-pink",
  amber: "text-amber",
  cyan: "text-cyan-ink",
  green: "text-green-ink",
  violet: "text-violet",
  muted: "text-muted-foreground",
};

/** A pulsing dot (working), a glowing one (idle and fine), a dim one (offline), or an amber one (needs attention). */
export function Dot({ state }: { state: "busy" | "online" | "offline" | "attention" }) {
  const look = {
    busy: "bg-cyan shadow-[0_0_6px_var(--cyan)] animate-pulse",
    online: "bg-green shadow-[0_0_6px_var(--green)]",
    offline: "bg-line",
    attention: "bg-amber shadow-[0_0_6px_var(--amber)]",
  }[state];
  return <span aria-hidden className={`size-2 shrink-0 rounded-full ${look}`} />;
}
