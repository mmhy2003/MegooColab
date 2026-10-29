"""MegooColab's release rules, for the release workflow and for whoever releases (docs/releasing.md).

    python tools/release/versions.py check                       the version files agree
    python tools/release/versions.py plan                        what needs releasing (key=value lines, for $GITHUB_OUTPUT)
    python tools/release/versions.py scoop VERSION CHECKSUMS     point the Scoop manifest at a runner release

Two products are released separately: MegooColab (the server, `VERSION`, kept equal to the backend's and the
frontend's own version) tagged vX.Y.Z, and the runner (`runner/VERSION`) tagged runner-vX.Y.Z.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = "mmhy2003/MegooColab"
RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SCOOP_MANIFEST = "runner/scoop/megoocolab-runner.json"
# what each product is made of: a change here since its last release needs a new version
PRODUCTS = {
    "app": {"tag": "v", "version_file": "VERSION", "paths": ["backend", "frontend", "deploy", "VERSION"]},
    "runner": {"tag": "runner-v", "version_file": "runner/VERSION", "paths": ["runner"]},
}


def parse(version: str) -> tuple[int, int, int] | None:
    """A release version is exactly X.Y.Z (a leading v allowed); anything else (dev, 0.1.0-dev+abc) is not one."""
    m = RELEASE.match(version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _read(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8").strip()


def check(root: Path) -> list[str]:
    errors = []
    app = _read(root, "VERSION")
    others = {
        "backend/pyproject.toml": tomllib.loads(_read(root, "backend/pyproject.toml"))["project"]["version"],
        "frontend/package.json": json.loads(_read(root, "frontend/package.json"))["version"],
    }
    for path, version in others.items():
        if version != app:
            errors.append(f"{path} says {version}, VERSION says {app}: they must be equal")
    for path in ("VERSION", "runner/VERSION"):
        if parse(_read(root, path)) is None:
            errors.append(f"{path} holds {_read(root, path)!r}, not a release version (X.Y.Z)")
    return errors


def _last_tag(root: Path, prefix: str) -> str | None:
    tags = [t for t in _git(root, "tag", "--list", f"{prefix}*").split() if parse(t.removeprefix(prefix))]
    return max(tags, key=lambda t: parse(t.removeprefix(prefix)), default=None)


def guard(root: Path) -> list[str]:
    """A product that changed since its last release must carry a new version."""
    errors = []
    for product in PRODUCTS.values():
        tag = _last_tag(root, product["tag"])
        if tag is None or _read(root, product["version_file"]) != tag.removeprefix(product["tag"]):
            continue
        changed = [p for p in _git(root, "diff", "--name-only", tag, "HEAD", "--", *product["paths"]).split()
                   if p != SCOOP_MANIFEST]
        if changed:
            errors.append(f"{', '.join(product['paths'])} changed since {tag} but {product['version_file']} is still "
                          f"{tag.removeprefix(product['tag'])}: bump it (e.g. {changed[0]})")
    return errors


def note_path(product: str, version: str) -> str:
    return f"docs/releases/{PRODUCTS[product]['tag']}{version}.md"


def plan(root: Path) -> dict[str, str]:
    """For each product: whether its version still needs a release, and that version."""
    errors = check(root) + guard(root)
    out: dict[str, str] = {}
    for name, product in PRODUCTS.items():
        version = _read(root, product["version_file"])
        needed = not _git(root, "tag", "--list", f"{product['tag']}{version}").strip()
        if needed and not (root / note_path(name, version)).is_file():
            errors.append(f"{note_path(name, version)} is missing: every release needs its release note")
        out[name] = "true" if needed else "false"
        out[f"{name}_version"] = version
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    return out


def update_scoop(manifest: Path, version: str, checksums: str) -> None:
    hashes = {name: digest for digest, name in (line.split() for line in checksums.splitlines() if line.strip())}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    base = f"https://github.com/{REPO}/releases/download/runner-v{version}"
    for arch, goarch in (("64bit", "amd64"), ("arm64", "arm64")):
        archive = f"megoocolab-runner_{version}_windows_{goarch}.zip"
        data["architecture"][arch] = {"url": f"{base}/{archive}", "hash": hashes[archive]}
    manifest.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    match argv:
        case ["check"]:
            errors = check(root)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            return 0
        case ["plan"]:
            print("\n".join(f"{k}={v}" for k, v in plan(root).items()))
            return 0
        case ["scoop", version, checksums]:
            update_scoop(root / SCOOP_MANIFEST, version, Path(checksums).read_text(encoding="utf-8"))
            return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
