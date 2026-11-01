"use client";

import Link from "next/link";

import { useOrigin, type Area } from "@/lib/backNav";

/** "← Back to …": where the person came from before reading in this area, else one level up. */
export function BackLink({ area, fallback }: { area: Area; fallback: { href: string; label: string } }) {
  const origin = useOrigin(area);
  const to = origin ? { href: origin.url, label: origin.label } : fallback;
  return (
    <Link href={to.href} className="inline-flex items-center rounded border border-line px-2 py-1 text-sm text-fg no-underline hover:border-cyan">
      ← Back to {to.label}
    </Link>
  );
}
