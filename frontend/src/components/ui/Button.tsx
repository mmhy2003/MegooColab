import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-cyan-ink text-on-accent border-cyan hover:glow-box dark:bg-cyan dark:text-on-accent",
  ghost: "bg-transparent text-cyan-ink border-line hover:border-cyan hover:bg-surface-2",
  danger: "bg-transparent text-pink border-pink/60 hover:bg-pink hover:text-on-accent",
};

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded border px-3 py-1.5 font-display text-xs font-semibold tracking-widest uppercase transition-shadow disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}
