"use client";

import { Info, Trash2, TriangleAlert, type LucideIcon } from "lucide-react";
import { useCallback, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";

export type Tone = "danger" | "warn" | "info";

export type AskOptions = {
  title: string;
  /** The consequence, below the title. */
  text?: React.ReactNode;
  /** The action's button, e.g. "Delete". */
  ok: string;
  /** The safe choice, focused when the dialog opens (default "Cancel"). */
  cancel?: string;
  /** danger: deleting or losing access (pink); warn: losing unsaved work (amber); info: anything else (cyan). */
  tone?: Tone;
  icon?: LucideIcon;
};

type TextField = { label: string; value: string };
type Pending = AskOptions & { field?: TextField; resolve: (answer: boolean | string | null) => void };

const ICON: Record<Tone, LucideIcon> = { danger: Trash2, warn: TriangleAlert, info: Info };
const ICON_STYLE: Record<Tone, string> = {
  danger: "bg-pink/15 text-pink",
  warn: "bg-amber/15 text-amber",
  info: "bg-cyan/15 text-cyan-ink",
};
// the action's button: solid pink when something is lost, the primary cyan otherwise
const OK_STYLE: Record<Tone, string> = {
  danger: "bg-pink border-pink text-white glow-box-pink dark:bg-pink dark:text-white hover:bg-pink",
  warn: "bg-pink border-pink text-white glow-box-pink dark:bg-pink dark:text-white hover:bg-pink",
  info: "",
};

/**
 * Questions as MegooColab dialogs instead of the browser's confirm() and prompt(): `ask` resolves true or false,
 * `askText` the trimmed text or null. Render `dialog` once in the component that asks. The safe choice is focused, so
 * a stray Enter never confirms; Escape or a click outside cancels.
 */
export function useConfirm(): {
  ask: (options: AskOptions) => Promise<boolean>;
  askText: (options: AskOptions & { field: TextField }) => Promise<string | null>;
  dialog: React.ReactNode;
} {
  const [pending, setPending] = useState<Pending | null>(null);
  const [text, setText] = useState("");

  const ask = useCallback(
    (options: AskOptions) =>
      new Promise<boolean>((resolve) => setPending({ ...options, resolve: (a) => resolve(a === true) })),
    [],
  );
  const askText = useCallback(
    (options: AskOptions & { field: TextField }) =>
      new Promise<string | null>((resolve) => {
        setText(options.field.value);
        setPending({ ...options, resolve: (a) => resolve(typeof a === "string" ? a : null) });
      }),
    [],
  );

  const dialog = pending && (
    <ConfirmDialog
      pending={pending}
      text={text}
      onText={setText}
      onAnswer={(answer) => {
        pending.resolve(answer);
        setPending(null);
      }}
    />
  );
  return { ask, askText, dialog };
}

function ConfirmDialog({
  pending,
  text,
  onText,
  onAnswer,
}: {
  pending: Pending;
  text: string;
  onText: (text: string) => void;
  onAnswer: (answer: boolean | string | null) => void;
}) {
  const tone = pending.tone ?? "info";
  const Icon = pending.icon ?? ICON[tone];
  const describedBy = useId();
  const field = useRef<HTMLInputElement>(null);
  const trimmed = text.trim();
  const confirm = () => onAnswer(pending.field ? trimmed : true);
  const cancel = () => onAnswer(pending.field ? null : false);
  return (
    <Dialog open title={pending.title} onClose={cancel} role="alertdialog" bare dismissible describedBy={pending.text ? describedBy : undefined}>
      <form
        className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3.5 gap-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation(); // never submit a form the asking component sits in
          if (!pending.field || trimmed) confirm();
        }}
      >
        <span data-tone={tone} aria-hidden className={`grid size-10 place-items-center rounded-full max-[420px]:hidden ${ICON_STYLE[tone]}`}>
          <Icon size={18} />
        </span>
        <div className="min-w-0 max-[420px]:col-span-2">
          <h2 className="mt-0.5 font-display text-base font-semibold">{pending.title}</h2>
          {pending.text && (
            <p id={describedBy} className="mt-1 text-sm text-muted-foreground">
              {pending.text}
            </p>
          )}
        </div>
        {pending.field && (
          <input
            ref={field}
            data-autofocus
            aria-label={pending.field.label}
            className="col-span-2 w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm"
            value={text}
            onChange={(e) => onText(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
          />
        )}
        <div className="col-span-2 mt-1 flex justify-end gap-2 max-[420px]:flex-col-reverse">
          <Button variant="ghost" className="text-muted-foreground" data-autofocus={pending.field ? undefined : true} onClick={cancel}>
            {pending.cancel ?? "Cancel"}
          </Button>
          <Button type="submit" className={OK_STYLE[tone]} disabled={!!pending.field && !trimmed}>
            {pending.ok}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
