import { useId } from "react";

/** A titled part of a task (Subtasks, Design, Attachments, Activity…), on its page and in a chat's rounds. Its heading
 * names it, so it is a region a screen reader (and a test) can find by name. */
export function Section({ title, id, children }: { title: string; id?: string; children: React.ReactNode }) {
  const heading = useId();
  return (
    <section id={id} aria-labelledby={heading} className="space-y-2">
      <h3 id={heading} className="text-[11px] tracking-widest text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}
