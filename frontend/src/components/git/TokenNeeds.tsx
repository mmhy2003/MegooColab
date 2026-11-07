"use client";

import { ExternalLink } from "lucide-react";
import { useId, useState } from "react";

import { HOST_NAME, newTokenUrl, TOKEN_DOCS, TOKEN_NEEDS, type GitKind } from "@/lib/git";

/**
 * What a connection's token needs, under its box: one row per reason (follow pull requests, webhooks in one click,
 * an agent's review and merge), each permission its own chip with its access, a button to the host's new-token page
 * (once there is an address to put it under) and the host's guide. GitHub offers a choice of token type.
 */
export function TokenNeeds({ kind, base }: { kind: GitKind; base: string }) {
  const variants = TOKEN_NEEDS[kind];
  const [picked, setPicked] = useState(0);
  const variant = variants[Math.min(picked, variants.length - 1)];
  const heading = useId();
  const create = newTokenUrl(base, variant.newTokenPath);
  return (
    <section aria-labelledby={heading} className="space-y-1 rounded-md border border-line bg-surface-2/60 p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-1">
        <h3 id={heading} className="font-semibold text-fg">What the token needs</h3>
        {variants.length > 1 && (
          <div role="group" aria-label="Token type" className="flex overflow-hidden rounded border border-line text-[13px]">
            {variants.map((v, i) => (
              <button
                key={v.label}
                type="button"
                aria-pressed={v === variant}
                onClick={() => setPicked(i)}
                className={`min-h-8 px-2.5 ${v === variant ? "bg-cyan/10 font-semibold text-cyan-ink" : "text-muted-foreground hover:text-fg"}`}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <ul className="divide-y divide-line">
        {variant.needs.map((need) => (
          <li key={need.why} className="grid gap-x-4 gap-y-2 py-3 sm:grid-cols-[11rem_minmax(0,1fr)]">
            <div className="flex items-start justify-between gap-2 sm:block">
              <p className="font-medium text-fg">{need.why}</p>
              <span
                className={`inline-block rounded-full px-2 text-[11px] sm:mt-1 ${need.required ? "bg-cyan/10 text-cyan-ink" : "bg-line text-muted-foreground"}`}
              >
                {need.required ? "Required" : "Optional"}
              </span>
            </div>
            <div className="min-w-0 space-y-2">
              {need.permissions.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {need.permissions.map((p) => (
                    <li key={p.name} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-0.5 text-[13px]">
                      <span className="text-fg">{p.name}</span>
                      {p.access && <span className={p.access === "Read" ? "text-cyan-ink" : "text-amber"}>{p.access}</span>}
                    </li>
                  ))}
                </ul>
              )}
              {need.note && <p className="text-[13px] text-muted-foreground">{need.note}</p>}
              {need.warning && (
                <p className="rounded-r border-l-2 border-amber bg-amber/5 px-2.5 py-1.5 text-[13px] text-fg">{need.warning}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
        {create && (
          <a
            href={create}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 rounded border border-cyan px-3 text-[13px] font-semibold text-cyan-ink no-underline hover:bg-cyan/10"
          >
            {variant.newTokenLabel}
            <ExternalLink size={13} aria-hidden />
          </a>
        )}
        <a href={TOKEN_DOCS[kind]} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[13px]">
          {HOST_NAME[kind]}&apos;s guide
          <ExternalLink size={12} aria-hidden />
        </a>
      </div>
    </section>
  );
}
