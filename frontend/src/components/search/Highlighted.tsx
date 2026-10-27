import { highlight } from "@/lib/search";

/** Text with search highlights: plain parts as text, matched words in <mark>. Never parsed as HTML. */
export function Highlighted({ text }: { text: string }) {
  return (
    <>
      {highlight(text).map((part, i) =>
        part.mark ? (
          <mark key={i} className="rounded-sm bg-cyan/25 px-0.5 text-fg">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}
