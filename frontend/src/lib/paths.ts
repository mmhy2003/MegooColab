/** A long folder path cut in the middle, so its end (the folder that matters) stays: "C:\…\Projects\checkout".
 * Keeps the first part and as many trailing parts as fit in `max` characters, and always the last one. */
export function middleTruncate(path: string, max: number): string {
  if (path.length <= max) return path;
  const sep = path.includes("\\") ? "\\" : "/";
  const parts = path.split(sep);
  // "/home/me/…" splits to ["", "home", …]: the first part is "/home"
  const rooted = parts[0] === "";
  const first = rooted ? `${sep}${parts[1] ?? ""}` : parts[0];
  const rest = parts.slice(rooted ? 2 : 1);
  if (rest.length < 2) return path;
  let tail = rest[rest.length - 1];
  for (let i = rest.length - 2; i > 0; i -= 1) {
    const longer = `${rest[i]}${sep}${tail}`;
    if (`${first}${sep}…${sep}${longer}`.length > max) break;
    tail = longer;
  }
  return `${first}${sep}…${sep}${tail}`;
}
