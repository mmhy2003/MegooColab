import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const SWATCHES = ["bg", "surface", "surface-2", "line", "fg", "muted-foreground", "cyan", "cyan-ink", "pink", "green", "green-ink", "amber"];

// Development aid: every theme token side by side. Toggle the theme to compare.
export default function TokensPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="mx-auto max-w-4xl space-y-6 p-6">
      <h1 className="text-2xl font-bold text-cyan-ink glow-cyan">
        MEGOO<span className="text-pink glow-pink">COLAB</span> tokens
      </h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {SWATCHES.map((name) => (
          <div key={name} className="card p-2">
            <div className="h-12 rounded border border-line" style={{ background: `var(--${name})` }} />
            <p className="mt-1 text-xs text-muted-foreground">--{name}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button>Primary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Badge tone="cyan">cyan</Badge>
        <Badge tone="pink">needs you</Badge>
        <Badge tone="green">online</Badge>
      </div>
    </main>
  );
}
