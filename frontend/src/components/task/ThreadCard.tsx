import { Surface } from "@/components/a2ui/Surface";
import type { ActivityCard } from "@/lib/types";

const CARD_FAILED = "This card couldn't be drawn. This is its text.";

/** A card an agent showed: its title as the heading, the surface read-only below; its text only when it can't be drawn. */
export function ThreadCard({ card }: { card: ActivityCard }) {
  return (
    <section data-thread-card aria-label={card.title} className="card mt-1 -ml-3.5 px-3 py-2 text-sm text-fg">
      <h3 className="mb-2 font-semibold">{card.title}</h3>
      <Surface
        message={card.surface}
        readOnly
        fallback={
          <div role="alert">
            <p>{card.text}</p>
            <p className="text-xs text-muted-foreground">{CARD_FAILED}</p>
          </div>
        }
      />
    </section>
  );
}
