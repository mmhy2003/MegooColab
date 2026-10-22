import { Avatar } from "@/components/ui/Avatar";
import { Markdown } from "@/components/ui/Markdown";
import type { ActivityItem } from "@/lib/types";

type Names = { columnNames: Map<string, string>; userNames: Map<string, string> };

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

/** Sentence fragment describing an event; unknown kinds (from later features) fall back to the kind itself. */
export function describeEvent(kind: string, data: Record<string, unknown>, { columnNames, userNames }: Names): string {
  switch (kind) {
    case "created":
      return "created this task";
    case "status_changed":
      return `moved this to ${columnNames.get(str(data.to_column) ?? "") ?? "another column"}`;
    case "assigned": {
      const to = str(data.to);
      return to ? `assigned this to ${userNames.get(to) ?? "someone"}` : "unassigned this";
    }
    case "field_changed": {
      const field = str(data.field) ?? "a field";
      const label = field.replace(/_md$/, "").replace(/_/g, " ");
      if ("to" in data && data.to !== null && typeof data.to !== "object" && field !== "parent_id") {
        return `changed ${label} to ${String(data.to)}`;
      }
      return `changed ${label}`;
    }
    case "sprint_changed":
      return data.to ? "moved this into a sprint" : "moved this to the backlog";
    default:
      return kind;
  }
}

function when(at: string): string {
  return new Date(at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function ActivityThread({ items, columnNames, userNames }: { items: ActivityItem[] } & Names) {
  return (
    <ol className="space-y-3">
      {items.map((item) => {
        const actor = item.actor?.name ?? "Someone";
        if (item.type === "comment") {
          return (
            <li key={item.id} className="flex gap-2">
              <Avatar name={actor} size={24} />
              <div className="card min-w-0 flex-1 px-3 py-2">
                <p className="text-xs text-muted">
                  <span className="text-fg">{actor}</span> · {when(item.at)}
                  {item.edited_at && <span className="ml-1">(edited)</span>}
                </p>
                <Markdown>{item.body_md ?? ""}</Markdown>
              </div>
            </li>
          );
        }
        return (
          <li key={item.id} className="flex items-center gap-2 pl-1 text-xs text-muted">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-cyan" />
            <span>
              <span className="text-fg">{actor}</span> {describeEvent(item.kind ?? "", item.data ?? {}, { columnNames, userNames })}
            </span>
            <span className="ml-auto whitespace-nowrap">{when(item.at)}</span>
          </li>
        );
      })}
    </ol>
  );
}
