import type { DashboardScope } from "@/lib/dashboard";

const OPTIONS: { value: DashboardScope; label: string }[] = [
  { value: "mine", label: "Mine" },
  { value: "teams", label: "My teams" },
  { value: "all", label: "Everything" },
];

/** Mine / My teams / Everything; Everything is offered to admins only. */
export function ScopeSwitch({ value, onChange, isAdmin }: { value: DashboardScope; onChange: (s: DashboardScope) => void; isAdmin: boolean }) {
  return (
    <div role="group" aria-label="Scope" className="inline-flex overflow-hidden rounded border border-line">
      {OPTIONS.filter((o) => isAdmin || o.value !== "all").map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`px-2.5 py-1 text-xs ${value === o.value ? "bg-surface-2 text-cyan-ink" : "text-muted-foreground hover:text-fg"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
