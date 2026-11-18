"use client";

import { Hint } from "@/components/ui/Hint";
import { useUpdates } from "@/lib/updates";
import { releaseUrl, versionLabel } from "@/lib/versions";

const LOOK = "text-xs whitespace-nowrap text-muted-foreground tabular-nums no-underline";

/** The MegooColab version the server runs, for everyone signed in ("I'm on v0.23.1" in a bug report). A release
 * links to its notes on GitHub; a build from source ("dev") has none, so it is plain text. Nothing while the version
 * is not known (loading, a failed request, a server older than this page). */
export function AppVersion({ className = "" }: { className?: string }) {
  const version = useUpdates().data?.app_version;
  const label = versionLabel(version);
  if (!label) return null;
  const url = releaseUrl(version);
  if (!url) {
    return (
      <span title={label} className={`inline-block max-w-[12ch] truncate align-middle ${LOOK} ${className}`}>
        <span className="sr-only">MegooColab </span>
        {label}
      </span>
    );
  }
  const number = label.slice(1);
  return (
    <Hint label={`MegooColab ${number}: release notes`}>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        aria-label={`MegooColab ${number}, release notes (opens in a new tab)`}
        className={`${LOOK} hover:text-cyan-ink hover:underline focus-visible:text-cyan-ink focus-visible:underline ${className}`}
      >
        {label}
      </a>
    </Hint>
  );
}
