"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Hint } from "@/components/ui/Hint";

/** A read-only, copyable block for commands and config files. */
export function Snippet({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs tracking-wider text-muted-foreground uppercase">{label}</span>
      <div className="flex gap-2">
        <textarea
          readOnly
          rows={value.split("\n").length}
          value={value}
          aria-label={label}
          wrap="off"
          className="min-w-0 flex-1 resize-none overflow-x-auto rounded border border-line bg-surface-2 px-2 py-1.5 font-mono text-xs"
          onFocus={(e) => e.target.select()}
        />
        <Hint label={copied ? `${label} copied` : `Copy ${label}`}>
          <button
            type="button"
            className="icon-btn self-start border border-line"
            aria-label={copied ? `${label} copied` : `Copy ${label}`}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(value);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              } catch {
                // clipboard blocked: the field is still selectable
              }
            }}
          >
            {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
          </button>
        </Hint>
      </div>
    </div>
  );
}
