import { useId, type SelectHTMLAttributes } from "react";

export function Select({
  label,
  id,
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  const auto = useId();
  const selectId = id ?? auto;
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={selectId} className="text-xs tracking-wider text-muted-foreground uppercase">
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={`w-full rounded border border-line bg-surface-2 px-2 py-2 text-sm text-fg focus:border-cyan focus:outline-none ${className}`}
        {...props}
      >
        {children}
      </select>
    </div>
  );
}
