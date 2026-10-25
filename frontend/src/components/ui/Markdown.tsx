import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders user/agent Markdown. Raw HTML is never rendered (react-markdown's default). */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-megoo text-sm leading-relaxed break-words [&_a]:underline [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_h1]:text-lg [&_h2]:text-base [&_li]:ml-5 [&_ol]:list-decimal [&_p]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-surface-2 [&_pre]:p-3 [&_ul]:list-disc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
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
