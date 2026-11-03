"use client";

import { ImagePlus } from "lucide-react";
import { createContext, useRef, useState } from "react";
import { flushSync } from "react-dom";

/** Lets the form inside close the bar again (CommentBox does after a send). Null outside a PhoneComposer. */
export const PhoneComposerContext = createContext<{ close: () => void } | null>(null);

/** On a phone the comment form takes too much of the screen to float over the task: it waits as a one-line bar
 * until tapped. The form stays mounted while closed, so a half-written comment is kept. From md up the bar never
 * shows and the form always does. */
export function PhoneComposer({ children, label }: { children: React.ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  const form = useRef<HTMLDivElement>(null);
  const textarea = () => form.current?.querySelector("textarea") ?? null;
  const show = (then?: () => void) => {
    // shown first (it is display:none on a phone while closed), so the focus and the file chooser land on it
    flushSync(() => setOpen(true));
    textarea()?.focus();
    then?.();
  };
  const close = () => setOpen(false);
  return (
    <PhoneComposerContext.Provider value={{ close }}>
      {!open && (
        <div className="flex items-center gap-2 md:hidden">
          <button
            type="button"
            onClick={() => show()}
            className="min-h-9 min-w-0 flex-1 truncate rounded border border-line bg-surface-2 px-3 text-left text-sm text-muted-foreground"
          >
            {label}
          </button>
          <button
            type="button"
            aria-label="Add images"
            onClick={() => show(() => form.current?.querySelector<HTMLInputElement>('input[type="file"]')?.click())}
            className="icon-btn size-9 shrink-0 rounded border border-line"
          >
            <ImagePlus size={16} aria-hidden />
          </button>
        </div>
      )}
      <div
        ref={form}
        data-phone-form
        className={open ? undefined : "max-md:hidden"}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) close();
        }}
        onBlur={(e) => {
          // tapping away from an empty comment folds it back; one with text stays open
          if (!open || form.current?.contains(e.relatedTarget as Node | null)) return;
          if (!textarea()?.value.trim()) close();
        }}
      >
        {children}
      </div>
    </PhoneComposerContext.Provider>
  );
}
