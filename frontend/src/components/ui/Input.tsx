import { forwardRef, useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

const FIELD =
  "w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { label?: string; error?: string }
>(function Input({ label, error, id, className = "", ...props }, ref) {
  const auto = useId();
  const inputId = id ?? auto;
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={inputId} className="text-xs tracking-wider text-muted-foreground uppercase">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        className={`${FIELD} ${className}`}
        {...props}
      />
      {error && <p className="text-xs text-pink">{error}</p>}
    </div>
  );
});

export function Textarea({
  label,
  id,
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  const auto = useId();
  const inputId = id ?? auto;
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={inputId} className="text-xs tracking-wider text-muted-foreground uppercase">
          {label}
        </label>
      )}
      <textarea id={inputId} className={`${FIELD} min-h-24 ${className}`} {...props} />
    </div>
  );
}
