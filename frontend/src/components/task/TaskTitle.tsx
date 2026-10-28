"use client";

import { useLayoutEffect, useRef } from "react";

// browsers without CSS field-sizing (Safari, older Firefox): size the box to its text in code
function fit(el: HTMLTextAreaElement | null) {
  if (!el || CSS.supports?.("field-sizing", "content")) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

/**
 * The task's editable title. A text area that grows with its text, so a long title wraps (on a phone, too) instead of
 * being cut; Enter saves rather than adding a line, since a title is one line of text. Saved on blur when changed.
 */
export function TaskTitle({ value, disabled, onSave }: { value: string; disabled?: boolean; onSave: (title: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => fit(ref.current), [value]);
  return (
    <textarea
      ref={ref}
      onInput={(e) => fit(e.currentTarget)}
      aria-label="Title"
      key={value}
      defaultValue={value}
      disabled={disabled}
      rows={1}
      className="mt-1 w-full resize-none overflow-hidden rounded border border-transparent bg-transparent px-1 font-display text-base text-fg [field-sizing:content] hover:border-line focus:border-cyan focus:outline-none"
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        }
      }}
      onBlur={(e) => {
        const title = e.target.value.trim();
        if (title && title !== value) onSave(title);
      }}
    />
  );
}
