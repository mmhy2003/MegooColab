"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useRef } from "react";

/**
 * A sandboxed agent mockup. `sandbox="allow-scripts"` only: no same-origin, popups or forms, so the page
 * runs with an opaque origin. The only way out is postMessage, and a message is passed on only when it comes
 * from this frame, from the opaque origin, with the right type and one of the mockup's declared choice ids.
 * `onChoice` is for preselecting: a mockup's script must never answer on a person's behalf. Without `onChoice`
 * (a shown mockup has no choices) no message is listened to at all.
 */
export function MockupFrame({
  mockupId,
  version,
  title,
  choices,
  onChoice,
}: {
  mockupId: string;
  version: number;
  title: string;
  choices?: string[];
  onChoice?: (choice: string) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const url = `/api/mockups/${mockupId}/view`;

  useEffect(() => {
    if (!onChoice || !choices?.length) return;
    const onMessage = (event: MessageEvent) => {
      const win = frame.current?.contentWindow;
      if (!win || event.source !== win || event.origin !== "null") return;
      const data: unknown = event.data;
      if (!data || typeof data !== "object") return;
      const { type, choice } = data as { type?: unknown; choice?: unknown };
      if (type !== "megoo-choice" || typeof choice !== "string" || !choices.includes(choice)) return;
      onChoice(choice);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [choices, onChoice]);

  return (
    <div className="space-y-1">
      <iframe
        ref={frame}
        sandbox="allow-scripts"
        src={url}
        title={`Mockup v${version}: ${title}`}
        className="h-[420px] w-full rounded border border-line bg-white"
      />
      <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-cyan-ink underline">
        Open full screen <ExternalLink size={12} aria-hidden />
      </a>
    </div>
  );
}
