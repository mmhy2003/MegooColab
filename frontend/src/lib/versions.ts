/** Release versions are exactly X.Y.Z (a leading v allowed). Anything else (dev, 0.1.0-dev+abc) is a build from
 * source, which is never "out of date". The backend's app/updates/versions.py follows the same rules. */
const RELEASE = /^v?(\d+)\.(\d+)\.(\d+)$/;

export function parseVersion(v?: string | null): [number, number, number] | null {
  const m = RELEASE.exec((v ?? "").trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

export function isNewer(latest?: string | null, current?: string | null): boolean {
  const a = parseVersion(latest);
  const b = parseVersion(current);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}

const RELEASES = "https://github.com/mmhy2003/MegooColab/releases/tag/";

/** The running version as shown: a release as "v0.23.1" (never "vv0.23.1"); anything else (dev, 0.24.0-dev+abc)
 * as it is, trimmed. */
export function versionLabel(v?: string | null): string {
  const r = parseVersion(v);
  return r ? `v${r.join(".")}` : (v ?? "").trim();
}

/** The release's notes on GitHub; null for a build from source, which has no release page. */
export function releaseUrl(v?: string | null): string | null {
  const r = parseVersion(v);
  return r ? `${RELEASES}v${r.join(".")}` : null;
}
