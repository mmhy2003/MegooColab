import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

/** Title lookups for [[doc:…]] links: readable documents carry their title; others render as restricted. */
export type WikiTitles = Record<string, { title?: string | null; readable: boolean }>;

// mirrors app/kb/service.py LINK_RE: [[PAY-12]] and [[doc:<uuid>]] / [[doc:<uuid>|Label]]
const WIKI_RE =
  /\[\[([A-Z][A-Z0-9]{1,9})-(\d{1,9})\]\]|\[\[doc:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\|([^\]\n]{0,200}))?\]\]/g;

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[]; data?: Record<string, unknown> };

/** The document ids a body links to, for one batched title lookup. */
export function wikiDocIds(body: string): string[] {
  const ids = new Set<string>();
  for (const m of body.matchAll(WIKI_RE)) if (m[3]) ids.add(m[3].toLowerCase());
  return [...ids].sort();
}

function wikiNodes(text: string, titles: WikiTitles): MdNode[] {
  const out: MdNode[] = [];
  let last = 0;
  for (const m of text.matchAll(WIKI_RE)) {
    if (m.index > last) out.push({ type: "text", value: text.slice(last, m.index) });
    if (m[1]) {
      out.push({ type: "link", url: `/projects/${m[1]}/tasks/${m[2]}`, children: [{ type: "text", value: `${m[1]}-${m[2]}` }] });
    } else {
      const id = m[3].toLowerCase();
      const info = titles[id];
      if (info && !info.readable) {
        out.push({ type: "text", value: "(restricted document)" });
      } else {
        const label = m[4]?.trim() || info?.title || "document";
        out.push({ type: "link", url: `/kb/doc/${id}`, children: [{ type: "text", value: label }] });
      }
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

/** A remark plugin: text outside links and code becomes task and document links. */
function remarkWikiLinks(titles: WikiTitles) {
  const walk = (node: MdNode) => {
    if (!node.children || node.type === "link" || node.type === "linkReference") return;
    node.children = node.children.flatMap((child) => {
      if (child.type === "text" && child.value?.includes("[[")) return wikiNodes(child.value, titles);
      walk(child);
      return [child];
    });
  };
  return () => (tree: MdNode) => walk(tree);
}

const textOf = (node: MdNode): string => node.value ?? (node.children ?? []).map(textOf).join("");

/** A remark plugin: a mention `@[Name](user:<uuid>)` becomes the text `@Name`, and any other `user:` link its
 * plain text. Neither is ever a link. */
function remarkMentions() {
  const walk = (node: MdNode) => {
    if (!node.children) return;
    const out: MdNode[] = [];
    for (const child of node.children) {
      if (child.type !== "link" || !child.url?.startsWith("user:")) {
        walk(child);
        out.push(child);
        continue;
      }
      const prev = out[out.length - 1];
      const at = prev?.type === "text" && Boolean(prev.value?.endsWith("@"));
      if (at) prev.value = prev.value!.slice(0, -1);
      out.push(at
        ? { type: "text", value: `@${textOf(child)}`, data: { hName: "span", hProperties: { className: ["font-semibold"] } } }
        : { type: "text", value: textOf(child) });
    }
    node.children = out;
  };
  return () => (tree: MdNode) => walk(tree);
}

/** Renders user/agent Markdown. Raw HTML is never rendered (react-markdown's default). With `wiki`, Knowledge
 * Base wiki links become links (titles come from `wiki`; a document the reader cannot open shows as restricted).
 * Mentions render as `@Name`. */
export function Markdown({ children, wiki }: { children: string; wiki?: WikiTitles }) {
  return (
    <div className="prose-megoo text-sm leading-relaxed break-words [&_a]:underline [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_h1]:text-lg [&_h2]:text-base [&_li]:ml-5 [&_ol]:list-decimal [&_p]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-surface-2 [&_pre]:p-3 [&_ul]:list-disc">
      <ReactMarkdown
        remarkPlugins={wiki ? [remarkGfm, remarkMentions(), remarkWikiLinks(wiki)] : [remarkGfm, remarkMentions()]}
        // data: images are the only ones that may render inline; the default transform would strip them
        urlTransform={(url, key) => (key === "src" && /^data:image\//i.test(url) ? url : defaultUrlTransform(url))}
        components={{
          // agent-written text must not make the browser fetch remote images (tracking, exfiltration)
          img: ({ src, alt }) =>
            typeof src === "string" && src.startsWith("data:image/") ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={src} alt={alt ?? ""} />
            ) : typeof src === "string" && src ? (
              <a href={src} rel="noopener noreferrer" target="_blank">{alt || src}</a>
            ) : (
              <span>{alt}</span>
            ),
        }}
      >{children}</ReactMarkdown>
    </div>
  );
}
