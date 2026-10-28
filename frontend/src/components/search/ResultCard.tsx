import Link from "next/link";

import { plain, type Hit } from "@/lib/search";

type PersonCard = { email: string; teams: { id: string; name: string }[] };
type AgentCard = { owner_name: string; projects: { id: string; key: string }[] };

/** People and agents have no page of their own: their search result opens this card in place. */
export function ResultCard({ hit, onNavigate }: { hit: Hit; onNavigate?: () => void }) {
  const name = plain(hit.title);
  if (hit.kind === "person") {
    const card = (hit.card ?? { email: "", teams: [] }) as PersonCard;
    return (
      <section aria-label={name} className="space-y-2 text-sm">
        <h3 className="font-semibold">{name}</h3>
        <p className="text-muted-foreground">{card.email}</p>
        {card.teams.length > 0 ? (
          <p>
            Teams:{" "}
            {card.teams.map((t, i) => (
              <span key={t.id}>
                {i > 0 && ", "}
                <Link href={`/teams/${t.id}`} onClick={onNavigate}>
                  {t.name}
                </Link>
              </span>
            ))}
          </p>
        ) : (
          <p className="text-muted-foreground">In no team</p>
        )}
      </section>
    );
  }
  const card = (hit.card ?? { owner_name: "", projects: [] }) as AgentCard;
  return (
    <section aria-label={name} className="space-y-2 text-sm">
      <h3 className="font-semibold">{name}</h3>
      <p className="text-muted-foreground">Owner: {card.owner_name}</p>
      {card.projects.length > 0 && (
        <p>
          Projects:{" "}
          {card.projects.map((p, i) => (
            <span key={p.id}>
              {i > 0 && ", "}
              <Link href={`/projects/${p.key}/board`} onClick={onNavigate}>
                {p.key}
              </Link>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}
