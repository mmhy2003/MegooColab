"use client";

import { useEffect, useId, useState, useSyncExternalStore } from "react";

import { MAX_DIAGRAM_CHARS } from "@/lib/mermaid";

type Mermaid = (typeof import("mermaid"))["default"];
let loading: Promise<Mermaid> | null = null;
let renders = 0;
// the library is large: it loads the first time a page has a diagram
const loadMermaid = () => (loading ??= import("mermaid").then((m) => m.default));

function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}
const isDark = () => document.documentElement.dataset.theme === "dark";

/** Mermaid fits a drawing to its box (up to its own width, the max-width it sets), which on a phone shrinks it past
 * reading: give it a floor of 40rem, or its own width if smaller, so a narrow screen scrolls sideways instead. Only
 * the opening <svg> tag is touched. */
function withReadableWidth(svg: string): string {
  return svg.replace(/^<svg\b[^>]*>/, (tag) => {
    const width = /max-width:\s*([\d.]+)px;?/.exec(tag);
    if (!width) return tag;
    return tag.replace(width[0], `max-width: ${width[1]}px; min-width: min(${width[1]}px, 40rem);`);
  });
}

type Drawn = { key: string; svg?: string; error?: string };

/** One Mermaid diagram, drawn in strict mode (agent-written text: no scripts, no click handlers), with a switch to
 * its code. A diagram that cannot be drawn, or is too large, shows its code and why. */
export function MermaidDiagram({ source }: { source: string }) {
  const id = "mermaid-" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const dark = useSyncExternalStore(subscribeTheme, isDark, () => false);
  const tooLarge = source.length > MAX_DIAGRAM_CHARS;
  const key = `${dark ? "dark" : "light"}:${source}`;
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const [showCode, setShowCode] = useState(false);

  useEffect(() => {
    if (tooLarge) return;
    let live = true;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
        await mermaid.parse(source); // throws on a mistake, before render leaves anything behind in the page
        // a fresh id each time: render removes any element that already has its id, such as the last drawing
        const { svg } = await mermaid.render(`${id}-${++renders}`, source);
        if (live) setDrawn({ key, svg: withReadableWidth(svg)});
      } catch (e) {
        const reason = (e instanceof Error ? e.message : String(e)).split("\n")[0].slice(0, 200);
        if (live) setDrawn({ key, error: reason || "unknown error" });
      }
    })();
    return () => {
      live = false;
    };
  }, [id, key, source, dark, tooLarge]);

  const code = (
    <pre>
      <code>{source}</code>
    </pre>
  );
  const current = drawn?.key === key ? drawn : null;
  const problem = tooLarge ? "This diagram is too large to draw here." : current?.error && `This diagram couldn't be drawn: ${current.error}`;

  if (problem) {
    return (
      <div className="my-2 overflow-hidden rounded border border-pink">
        <p className="bg-surface-2 px-3 py-1.5 text-xs text-pink">{problem}</p>
        {code}
      </div>
    );
  }
  return (
    <div className="my-2 overflow-hidden rounded border border-line">
      <div className="flex items-center justify-between bg-surface-2 px-3 py-1 text-xs text-muted-foreground">
        <span>Diagram</span>
        <span className="inline-flex overflow-hidden rounded border border-line">
          {(["Diagram", "Code"] as const).map((label) => {
            const on = (label === "Code") === showCode;
            return (
              <button
                key={label}
                type="button"
                aria-pressed={on}
                onClick={() => setShowCode(label === "Code")}
                className={on ? "bg-cyan px-2 py-0.5 text-on-accent" : "px-2 py-0.5 hover:text-fg"}
              >
                {label}
              </button>
            );
          })}
        </span>
      </div>
      {showCode ? (
        code
      ) : current?.svg ? (
        <div className="overflow-x-auto p-3 [&_svg]:mx-auto [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: current.svg }} />
      ) : (
        <p className="p-3 text-xs text-muted-foreground">Drawing diagram…</p>
      )}
    </div>
  );
}
